#!/bin/bash 
# Wait before start 
sleep 60 
# Assign License to server 
#HOSTNAME=$(hostname)echo $HOSTNAME 
#HOSTUUID=$(xe host-list name-label=$HOSTNAME --minimal) 
#xe host-apply-edition edition=platinum host-uuid=$HOSTUUID license-server-address=172.16.10.10 license-server-port=27000 
 
# Disable first boot script for subsequent reboots 
rm -f /etc/rc3.d/S99zzpostinstall 
 
# Final Reboot 
reboot
