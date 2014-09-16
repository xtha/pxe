#!/bin/bash 
# Install XenServer Updates 
HOSTUUID=$(xe host-list name-label=$HOSTNAME --minimal) 
cd /tmp 
if [ -a /tmp/secondboot ] 
then 
	echo "Secondboot" 
else 
	mkdir updates 
	cd updates 
	echo "Downloading Updates..." 
	wget http://192.168.11.11/xs602/postinstall.updates/*.xsupdate 
	cd /tmp 
	touch /tmp/secondboot 
fi 
for updatefile in `ls /tmp/updates`; do 
	sleep 60 
	echo "Uploading Update $updatefile ..." 
	echo "Uploading Update $updatefile ..." >> /var/log/messages 
	PATCHUUID=$(xe patch-upload file-name=/tmp/updates/$updatefile) 
	sleep 10 
	echo "Installing Update $updatefile ..." 
	echo "Installing Update $updatefile ...">> /var/log/messages 
	xe patch-apply host-uuid=$HOSTUUID uuid=$PATCHUUID 
	rm -f /tmp/updates/$updatefile 
	PATCHACTION=$(xe patch-list uuid=$PATCHUUID params=after-apply-guidance --minimal) 
	if [ "$PATCHACTION" == "restartXAPI" ]  
	then 
		/opt/xensource/bin/xe-toolstack-restart 
		sleep 60 
	elif [ "$PATCHACTION" == "restartHost" ]; then 
		reboot; 
	fi 
done 

# Disable first boot script for subsequent reboots 
rm -f /etc/rc3.d/S99zzpostinstall 
rm -f /tmp/secondboot 

# Final Reboot 
reboot 
