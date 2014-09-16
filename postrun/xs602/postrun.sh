#!/bin/sh 
touch $1/tmp/post-executed 
wget http://192.168.14.250/pxe/postrun/xs602/first-boot-script-602-std.sh -O $1/tmp/first-boot-script.sh 
chmod 777 $1/tmp/first-boot-script.sh 
ln -s /tmp/first-boot-script.sh $1/etc/rc3.d/S99zzpostinstall 
