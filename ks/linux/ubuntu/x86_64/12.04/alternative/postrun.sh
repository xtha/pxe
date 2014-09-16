#!/bin/bash
wget -P /etc/apt/apt.conf.d/ http://10.24.4.84/saltstack/etc/apt/apt.conf.d/00proxy
wget -O /etc/apt/sources.list http://10.24.4.84/saltstack/etc/apt/sources.list-precise
wget -O /etc/init.d/first-boot.sh http://10.24.4.84/pxe/ks/linux/ubuntu/12.04.1/x86_64/first-boot.sh
apt-get update
apt-get install -y xinetd build-essential ethtool dmidecode ntp
chmod a+x /etc/init.d/first-boot.sh
ln -s /etc/init.d/first-boot.sh /etc/rc2.d/S99first-boot.sh
