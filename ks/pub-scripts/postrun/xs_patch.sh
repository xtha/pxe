#!/bin/bash

host_name=`hostname | cut -d. -f1`
host_id=`xe host-list params=uuid | head -1 | cut -d ' ' -f8`
