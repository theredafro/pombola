#!/bin/bash

# abort on any errors
set -e

# check that we are in the expected directory
cd `dirname $0`/..

./bin/run_management_command pombola_sayit_sync_pombola_to_popolo
./bin/run_management_command popolo_name_resolver_init

./bin/run_management_command za_hansard_check_for_new_sources_from_pmg
./bin/run_management_command za_hansard_run_parsing
./bin/run_management_command za_hansard_load_into_sayit

# Run the ZA Hansard questions importer (all steps)
./bin/run_management_command za_hansard_q_and_a_scraper --run-all-steps

# Run the committee minutes scraper and imports
./bin/run_management_command za_hansard_pmg_api_scraper --scrape --save-json --import-to-sayit --delete-existing --commit
