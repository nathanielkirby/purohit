#!/usr/bin/env bash

python scripts/init_project.py \
  --hosts $HOME/Projects/Codes/purohit/scripts/hosts.yaml \
  --source-host cit \
  --source-dir /home/pe.o4/GWTC5-HLV \
  --project-dir $HOME/Projects/ligo/purohit_gwtc5 \
  --apx IMRPhenomXPHM
