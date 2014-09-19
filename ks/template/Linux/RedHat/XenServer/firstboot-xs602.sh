#!/bin/bash

ntpdate -u 192.168.11.10
hwclock -w

#echo "server 192.168.11.10" >> /etc/ntp.conf
#echo "server ntp.fudan.edu.cn" >> /etc/ntp.conf
echo "192.168.11.10" > /etc/ntp/step-tickers
sed -i '/stratum/s/10/5/' /etc/ntp.conf
service ntpd restart
#
host_id=`xe host-list params=uuid | head -1 | cut -d ' ' -f8`
host_name=`hostname | cut -d. -f1`
`xe host-param-set other-config:iscsi_iqn=iqn.2013-07.com.gdcloud:${host_name} uuid=${host_id}`
xe host-param-get param-name=other-config uuid=${host_id}
#
wget -P /tmp/ http://192.168.11.9/isos/tools/xenserver-cloud-supp.iso
xe-install-supplemental-pack /tmp/xenserver-cloud-supp.iso
#
wget -P /tmp/ http://nagios01.gdcloud.com/isos/hypervisor/xs602-2013-3-12.xslic
xe host-license-add license-file=/tmp/xs602-2013-3-12.xslic host-uuid=${host_id}
#
sed -i '/enabled/s/1/0/' /etc/yum.repos.d/Citrix.repo
rm -f /etc/yum.repos.d/CentOS-Base.repo
wget -P /etc/yum.repos.d/ http://192.168.11.9/repo/CentOS-Base.repo
yum makecache
#
umount /var/xen/xc-install 2>/dev/null
sed -i '/xc-install/d' /etc/fstab
#
`modprobe ipmi_si`
`modprobe ipmi_msghandler`
`modprobe ipmi_watchdog`
`modprobe ipmi_poweroff`
`modprobe ipmi_devintf`

echo "modprobe ipmi_msghandler" >> /etc/rc.local
echo "modprobe ipmi_si" >> /etc/rc.local
echo "modprobe ipmi_watchdog" >> /etc/rc.local
echo "modprobe ipmi_poweroff" >> /etc/rc.local
echo "modprobe ipmi_devintf" >> /etc/rc.local

#lsomod |grep ipmi
#ipmitool lan print
#
mv /etc/sysconfig/iptables /etc/syconfig/iptables.old
wget -P /etc/sysconfig/ http://10.24.4.84/pxe/scripts/postrun/xs60-iptables
mv /etc/sysconfig/xs60-iptables /etc/sysconfig/iptables
iptables-restore < /etc/sysconfig/iptables
#
yum --noplugins install xinetd smartmontools -y 1>&2 > /dev/null
rpm -ivh http://192.168.11.9/tools/nagios/cmk/agent/1.2.3i/check_mk-agent-1.2.3i1-1.noarch.rpm
#
mount -t nfs 192.168.11.9:/mnt/isos/updates /mnt
cd /mnt/xs_patcher && ./xs_patcher.sh
