from pydoc import describe
import yaml
import argparse
import sys
import re
import json 
import csv
import uuid
from os import path, walk
from tqdm import tqdm
from datetime import datetime


def read_lolbas(LOLBAS_PATH, VERBOSE):
    types = ["OSBinaries", "OSLibraries", "OSScripts", "OtherMSBinaries"]
    manifest_files = []
    for t in types:
        for root, dirs, files in walk(LOLBAS_PATH + '/yml/' + t):
            for file in files:
                if file.endswith(".yml"):
                    manifest_files.append((path.join(root, file)))

    lolbas = []
    for manifest_file in tqdm(manifest_files):
        lolba_yaml = dict()
        if VERBOSE:
            print("processing lolba yaml {0}".format(manifest_file))

        with open(manifest_file, 'r') as stream:
            try:
                object = list(yaml.safe_load_all(stream))[0]
                object['file_path'] = manifest_file
            except yaml.YAMLError as exc:
                print(exc)
                print("Error reading {0}".format(manifest_file))
                sys.exit(1)
        lolba_yaml = object
        lolbas.append(lolba_yaml)
    return lolbas

def get_lolbas_paths(lolba):
    lolbas_paths = []
    if 'Full_Path' in lolba:
            for fullpath in lolba['Full_Path']:
                # check path is not none
                if fullpath['Path']:
                    # check path is in c:\ there are some entries with N/A, No fixed path etc. . we should skip those
                    if re.findall('c:', fullpath['Path'], re.IGNORECASE):
                        lolbas_paths.append(fullpath['Path'])
    return lolbas_paths
    
                        
def write_ba_detections(lolbas, TEMPLATE_PATH, VERBOSE, OUTPUT_PATH):

    for lolba in lolbas:
        lolbas_path_strings = '' 
        full_ssa_search = ''
        # windows_lolbin_binary_in_non_standard_path auto search generation
        # first process SSA search
        ssa_base_search = '| from read_ssa_enriched_events() | eval device=ucast(map_get(input_event, "dest_device_id"), "string", null), user=ucast(map_get(input_event, "dest_user_id"), "string", null), timestamp=parse_long(ucast(map_get(input_event, "_time"), "string", null)), process_name=lower(ucast(map_get(input_event, "process_name"), "string", null)), process_path=lower(ucast(map_get(input_event, "process_path"), "string", null)), event_id=ucast(map_get(input_event, "event_id"), "string", null)'
        ssa_end_search ='| eval start_time=timestamp,end_time=timestamp, entities=mvappend(device, user), body=create_map(["event_id", event_id, "process_path", process_path, "process_name", process_name]) | into write_ssa_detected_events();'
        condition_1 = '| where process_name IS NOT NULL AND '
        condition_2 = '| where process_path IS NOT NULL AND '
        if get_lolbas_paths(lolba):
            full_paths = get_lolbas_paths(lolba)
            for full_path in full_paths:
                # grab the exe name
                lolbas_exe = 'process_name="' + lolba['Name'].lower() + '"'

                # drop the drive letter
                full_path = full_path[2:]

                # drop the exe at the end
                full_path = full_path.split("\\")[:-1]

                # rejoin to a path
                full_path = "\\".join(full_path)

                # adds a slash for regex at the end
                full_path = full_path.lower() + '/'
                # add path escapes
                full_path = full_path.replace("\\", "\\\\").lower()
                lolbas_path_strings = 'match_regex(process_path, /(?i)' + full_path + ')=false AND '
                #print("lolbas: " + lolba['Name'].lower() + " - full_path: " + lolbas_path_strings)

            # remove trailing OR and merge with condition
            condition_1 = condition_1 + lolbas_exe
                # remove trailing AND nd merge with condition
            condition_2 = condition_2 + lolbas_path_strings[:-4]
            full_ssa_search = ssa_base_search + condition_1 + condition_2 + ssa_end_search 
            lolba['full_ssa_search'] = full_ssa_search
            write_yaml(lolba, OUTPUT_PATH, TEMPLATE_PATH, VERBOSE)
        else:
            continue

def write_ba_tests(lolbas, TEMPLATE_PATH, VERBOSE, OUTPUT_PATH):
     for lolba in lolbas:
        # READ test template
        with open(TEMPLATE_PATH, 'r') as stream:
            try:
                object = list(yaml.safe_load_all(stream))[0]
                object['file_path'] = TEMPLATE_PATH
            except yaml.YAMLError as exc:
                print(exc)
                print("Error reading {0}".format(TEMPLATE_PATH))
                sys.exit(1)
        test_yaml_template = object


        # BA filename
        ba_test_path = OUTPUT_PATH + "/" + "ssa___" + lolba['Name'].lower().replace(".", "_") + ".test.yml"

        # Build the BA test objects
        test_yaml = test_yaml_template
        # change file path
        test_yaml['file'] = "endpoint/" + "ssa___" + lolba['Name'].lower().replace(".", "_") + ".yml"
        # change name
        test_yaml['name'] = "Windows Rename System Utilities " + lolba['Name'].replace(".", " ").capitalize() + " LOLBAS in Non Standard Path Unit Test"
        # change test name
        test_yaml['tests'][0]['name'] = "Windows Rename System Utilities " + lolba['Name'].replace(".", " ").capitalize() + " LOLBAS in Non Standard Path"
        # change test file path
        test_yaml['tests'][0]['file'] = "endpoint/" + "ssa___" + lolba['Name'].lower().replace(".", "_") + ".yml"
        # change test description
        test_yaml['tests'][0]['description'] = " Test Windows Rename System Utilities " + lolba['Name'].replace(".", " ").capitalize() + " LOLBAS in Non Standard Path"

        with open(ba_test_path, 'w', newline='') as yamlfile:
            if VERBOSE:
                print("writing BA test: {0}".format(ba_test_path))
            yaml.safe_dump(test_yaml, yamlfile, default_flow_style=False, sort_keys=False)

def write_dataset_file(lolbas, VERBOSE, OUTPUT_PATH):

    test_datasets = [] 
    for lolba in lolbas:
        # READ test template
        with open('test_dataset_template.log', 'r') as file:
            test_dataset_template = file.read()
        
        lolba_exe = lolba['Name'].lower().replace('(', '').replace(')', '')
        replaced = test_dataset_template.replace("xxx", lolba_exe)
        test_datasets.append(replaced)

    with open(OUTPUT_PATH + '/lolbas_dataset.log', 'wt', encoding='utf-8') as file:
        if VERBOSE:
            print("writing Attack Dataset: {0}".format( OUTPUT_PATH + '/lolbas_dataset.log'))
        file.write('\n'.join(test_datasets))
        

def write_yaml(lolba, OUTPUT_PATH, TEMPLATE_PATH, VERBOSE):
    # READ detection template

    with open(TEMPLATE_PATH, 'r') as stream:
        try:
            object = list(yaml.safe_load_all(stream))[0]
            object['file_path'] = TEMPLATE_PATH
        except yaml.YAMLError as exc:
            print(exc)
            print("Error reading {0}".format(TEMPLATE_PATH))
            sys.exit(1)
    detection_yaml_template = object


    # BA filename
    ba_detection_path = OUTPUT_PATH + "/" + "ssa___" + lolba['Name'].lower().replace(".", "_") + ".yml"

    # Build the BA objects
    detection_yaml = detection_yaml_template
    # change search
    detection_yaml['search'] = lolba['full_ssa_search']
    # change name
    detection_yaml['name'] = "Windows Rename System Utilities " + lolba['Name'].replace(".", " ").capitalize() + " LOLBAS in Non Standard Path"
    # generate a UUID per detection
    detection_yaml['id'] = str(uuid.uuid4())
    # generate a timestamp
    detection_yaml['date'] = datetime.today().strftime('%Y-%m-%d')
    # update description
    detection_yaml['description'] = detection_yaml_template['description'].replace("xxx", lolba['Name'])

    with open(ba_detection_path, 'w', newline='') as yamlfile:
        if VERBOSE:
            print("writing BA detection: {0}".format(ba_detection_path))
        yaml.safe_dump(detection_yaml, yamlfile, default_flow_style=False, sort_keys=False)


def write_csv(lolbas, OUTPUT_PATH):
    with open(OUTPUT_PATH + '/' + 'lolbas_file_path.csv', 'w', newline='') as csvfile:
        fieldnames = ['lolbas_file_name', 'lolbas_file_path', 'description']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for lolba in lolbas:
            parent_paths = []
            if get_lolbas_paths(lolba):
                full_paths = get_lolbas_paths(lolba)
                for full_path in full_paths:
                    # drop the exe at the end
                    parent_path_split = full_path.split("\\")[:-1]
                    # rejoin to a path
                    parent_path = "\\".join(parent_path_split)
                    # adds a asterisk at the end
                    parent_path = parent_path + '\\*'
                    if parent_path not in parent_paths:
                        parent_paths.append(parent_path)
                        lolba_file_name = lolba['Name'].lower()
                        lolba_description = lolba['Description']
                        writer.writerow({'lolbas_file_name': lolba_file_name, 'lolbas_file_path': parent_path.lower(), 'description': lolba_description})

        

if __name__ == "__main__":

    # grab arguments
    parser = argparse.ArgumentParser(description="Generates Updates Splunk detections with latest LOLBAS")
    parser.add_argument("--lolbas_path", required=False, default='LOLBAS', help="path to the lolbas repo")
    parser.add_argument("-o", "--output_path", required=False, default='output', help="path to results")
    parser.add_argument("--ba_template_path", required=False, default='ba_detection_template.yml', help="path to BA detection template")
    parser.add_argument("--ba_test_template_path", required=False, default='ba_test_template.yml', help="path to BA test template")
    parser.add_argument("-v", "--verbose", required=False, default=False, action='store_true', help="prints verbose output")
    
   # parse them
    args = parser.parse_args()
    LOLBAS_PATH = args.lolbas_path
    VERBOSE = args.verbose
    OUTPUT_PATH = args.output_path
    BA_TEMPLATE_PATH = args.ba_template_path
    BA_TEST_PATH = args.ba_test_template_path

    if not (path.isdir(OUTPUT_PATH) or path.isdir(OUTPUT_PATH)):
        print("error: {0} is not a directory".format(OUTPUT_PATH))
        sys.exit(1)

    print("processing lolbas")
    lolbas = read_lolbas(LOLBAS_PATH, VERBOSE)

    print("writing BA lolbas detections to: {0}/".format(OUTPUT_PATH))
    write_ba_detections(lolbas, BA_TEMPLATE_PATH, VERBOSE, OUTPUT_PATH)

    print("writing BA lolbas test files to: {0}/".format(OUTPUT_PATH))
    write_ba_tests(lolbas, BA_TEST_PATH, VERBOSE, OUTPUT_PATH)

    print("writing Attack Data logs to: {0}".format(OUTPUT_PATH + '/' + 'lolbas_dataset.log'))
    write_dataset_file(lolbas, VERBOSE, OUTPUT_PATH)

    print("writing ESCU lolbas_file_path lookup to: {0}".format(OUTPUT_PATH + '/' + 'lolbas_file_path.csv'))
    write_csv(lolbas, OUTPUT_PATH)
