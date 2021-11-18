
import git
import os
import logging
import glob
import subprocess
from git.objects import base
import yaml
import pathlib
import csv
# Logger
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
LOGGER = logging.getLogger(__name__)

SECURITY_CONTENT_URL = "https://github.com/splunk/security_content"


class GithubService:

    def __init__(self, security_content_branch:str, PR_number:int = None, existing_directory:bool=False):
        
        self.security_content_branch = security_content_branch
        if existing_directory:
            return
        print("Checking out security_content!")
        self.security_content_repo_obj = self.clone_project(SECURITY_CONTENT_URL, f"security_content", f"develop")

        if PR_number:
            subprocess.call(["git", "-C", "security_content/", "fetch", "origin", "refs/pull/%d/head:%s"%(PR_number, security_content_branch)])

        self.security_content_repo_obj.git.checkout(security_content_branch)

    def clone_project(self, url, project, branch):
        LOGGER.info(f"Clone Security Content Project")
        repo_obj = git.Repo.clone_from(url, project, branch=branch)
        return repo_obj

    

    def prune_detections(self, 
                         detections_to_prune:list[str], 
                         ttps_to_test:list[str], 
                         previously_successful_tests:list[str],
                         exclude_ssa:bool=True,
                         summary_file:str=None)->list[str]:
        pruned_tests = []
        csvlines = []
        for detection in detections_to_prune:
            if os.path.basename(detection).startswith("ssa") and exclude_ssa:
                continue
            with open(detection, "r") as d:
                description = yaml.safe_load(d)
                
                test_filepath = os.path.splitext(detection)[0].replace('detections', 'tests') + '.test.yml'
                test_filepath_without_security_content = str(pathlib.Path(*pathlib.Path(test_filepath).parts[1:]))
                #If no TTPS are provided, then we will get everything
                if 'type' in description and (description['type'] in ttps_to_test or len(ttps_to_test) == 0):
                    #print(description['type'])
                    if not os.path.exists(test_filepath):
                        print("Detection [%s] references [%s], but it does not exist"%(detection, test_filepath))
                        #raise(Exception("Detection [%s] references [%s], but it does not exist"%(detection, test_filepath)))
                    elif test_filepath_without_security_content in previously_successful_tests:
                        print("Ignoring test [%s] before it has already passed previously"%(detection))
                    else:
                        #remove leading security_content/ from path
                        pruned_tests.append(test_filepath_without_security_content)
                        if summary_file is not None:
                            try:
                                mitre_id = str(description['tags']['mitre_attack_id'])
                            except:
                                mitre_id = 'NONE'
                            try:

                                csvlines.append({'name':description['name'], 'filename':detection, 'description':description['description'], 
                                                 'search':description['search'], 'mitre_attack_id':mitre_id, 'security_domain':description['tags']['security_domain'],
                                                 'Relevant':'', 'Comments':'', "Runnable on SSA?": str(os.path.basename(detection).startswith("ssa"))})
                            except Exception as e:
                                print("Error outputting summary for [%s]: [%s]"%(detection, str(e))) 
                else:
                    #Don't do anything with these files
                    pass
        
        if summary_file is not None:
            print("writing")
            with open(summary_file, 'w') as csvfile:
                fieldnames = ['name', 'filename', 'description', 'search', 'mitre_attack_id', 'security_domain', 'Runnable on SSA?', 'Relevant', 'Comments']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for r in csvlines:
                    writer.writerow(r)
            
        
        return pruned_tests


    def get_selected_test_files(self,
                                detection_file_list:list[str], 
                                ttps_to_test:list[str]=["Anomaly","Hunting","TTP"], 
                                previously_successful_tests:list[str]=[]) ->list[str]:    
        
        return self.prune_detections(detection_file_list, ttps_to_test, previously_successful_tests)


    def get_all_tests_and_detections(self, 
                                     folders:list[str]=['endpoint', 'cloud', 'network'], 
                                     ttps_to_test:list[str]=["Anomaly","Hunting","TTP"], 
                                     previously_successful_tests:list[str]=[]) ->list[str]:    
        detections = []
        for folder in folders:
            detections.extend(self.get_all_files_in_folder(os.path.join("security_content/detections", folder), "*.yml"))
            
        
        #Prune this down to only the subset of detections we can test
        return self.prune_detections(detections, ttps_to_test, previously_successful_tests)
        
    def get_all_files_in_folder(self, foldername:str, extension:str)->list[str]:
        filenames =  glob.glob(os.path.join(foldername, extension))
        return filenames


    def get_changed_test_files(self, folders=['endpoint', 'cloud', 'network'], ttps_to_test=["Anomaly","Hunting","TTP"], previously_successful_tests=[])->list[str]:
        branch1 = self.security_content_branch
        branch2 = 'develop'
        g = git.Git('security_content')
        changed_test_files = []
        changed_detection_files = []
        if branch1 != 'develop':
            differ = g.diff('--name-status', branch2 + '...' + branch1)
            changed_files = differ.splitlines()

            for file_path in changed_files:
                # added or changed test files
                if file_path.startswith('A') or file_path.startswith('M'):
                    if 'tests' in file_path and os.path.basename(file_path).endswith('.test.yml'):
                            changed_test_files.append(file_path)

                    # changed detections
                    if 'detections' in file_path and os.path.basename(file_path).endswith('.yml'):
                            changed_detection_files.append(file_path)
        else:
            print("Looking for changed detections by diffing [%s] against [%s].  Of course none were returned."%(branch1, branch2))
            return []
                            

        #all files have the format A\tFILENAME or M\tFILENAME.  Get rid of those leading characters
        changed_test_files      = [os.path.join("security_content",name.split('\t')[1]) for name in changed_test_files      if len(name.split('\t')) == 2]
        changed_detection_files = [os.path.join("security_content",name.split('\t')[1]) for name in changed_detection_files if len(name.split('\t')) == 2]


        #convert the test files to the detection file equivalent
        converted_test_files = []
        for test_filepath in changed_test_files:
            detection_filename = str(pathlib.Path(*pathlib.Path(test_filepath).parts[-2:])).replace("tests", "detections",1)
            converted_test_files.append(detection_filename)

        for name in converted_test_files:
            if name not in changed_detection_files:
                changed_detection_files.append(name)

        return self.prune_detections(changed_detection_files, ttps_to_test, previously_successful_tests)

        #detections_to_test,_,_ = self.filter_test_types(changed_detection_files)
        #for f in detections_to_test:
        #    file_path_base = os.path.splitext(f)[0].replace('detections', 'tests') + '.test'
        #    file_path_new = file_path_base + '.yml'
        #    if file_path_new not in changed_test_files:
        #        changed_test_files.append(file_path_new)

        
        
       
        
        #print("Total things to test (test files and detection files changed): [%d]"%(len(changed_test_files)))
        #for l in changed_test_files:
        #    print(l)
        #print(len(changed_test_files))
        #import time
        #time.sleep(5)
        

    def filter_test_types(self, test_files, test_types = ["Anomaly", "Hunting", "TTP"]):
        files_to_test = []
        files_not_to_test = []
        error_files = []
        for filename in test_files:
            try:
                with open(os.path.join("security_content", filename), "r") as fileData:
                    yaml_dict = list(yaml.safe_load_all(fileData))[0]
                    if 'type' not in yaml_dict.keys():
                        print("Failed to find 'type' in the yaml for: [%s]"%(filename))
                        error_files.append(filename)
                    if yaml_dict['type'] in test_types:
                        files_to_test.append(filename)
                    else:
                        files_not_to_test.append(filename)
            except Exception as e:
                print("Error on trying to scan [%s]: [%s]"%(filename, str(e)))
                error_files.append(filename)
        print("***Detection Information***\n"\
              "\tTotal Files       : %d"
              "\tFiles to test     : %d"
              "\tFiles not to test : %d"
              "\tError files       : %d"%(len(test_files), len(files_to_test), len(files_not_to_test), len(error_files)))
        import time
        time.sleep(5)
        return files_to_test, files_not_to_test, error_files    



                



