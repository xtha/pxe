#!/bin/bash
#########################
# set yum centos'repo for RHEL
#########################
mv /etc/yum.conf /tmp
mv /etc/yum.repos.d/* /tmp
#wget http://mirrors.sohu.com/centos/6/os/x86_64/Packages/python-iniparse-0.3.1-2.1.el6.noarch.rpm
#wget http://mirrors.sohu.com/centos/6/os/x86_64/Packages/yum-metadata-parser-1.1.2-16.el6.x86_64.rpm
#wget http://mirrors.sohu.com/centos/6/os/x86_64/Packages/yum-3.2.29-40.el6.centos.noarch.rpm
#wget http://mirrors.sohu.com/centos/6/os/x86_64/Packages/yum-plugin-fastestmirror-1.1.30-14.el6.noarch.rpm
#yum install --nogpgcheck -y yum-priorities 
wget -O /etc/yum.conf http://10.24.4.84/pxe/saltstack/etc/yum.conf
wget -O /etc/yum.repos.d/CentOS-Base.repo http://10.24.4.84/pxe/saltstack/etc/yum.repos.d/CentOS-Base.repo
wget -O /etc/yum.repos.d/epel.repo http://10.24.4.84/pxe/saltstack/etc/yum.repos.d/epel.repo
wget -O /etc/yum.repos.d/rpmforge.repo http://10.24.4.84/pxe/saltstack/etc/yum.repos.d/rpmforge.repo
wget -P /etc/pki/rpm-gpg http://10.24.4.84/pxe/saltstack/etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
wget -P /etc/pki/rpm-gpg http://10.24.4.84/pxe/saltstack/etc/pki/rpm-gpg/RPM-GPG-KEY-EPEL-6
wget -P /etc/pki/rpm-gpg http://10.24.4.84/pxe/saltstack/etc/pki/rpm-gpg/RPM-GPG-KEY-rpmforge-dag
yum makecache
#########################
# set xrdp & vncserver
#########################
yum install -y wget kexec-tools sos pixman libXfont tigervnc-server xrdp --nogpgcheck
wget -O /etc/sysconfig/vncservers http://10.24.4.84/pxe/saltstack/etc/sysconfig/vncservers

chkconfig xrdp on
chkconfig vncserver on
service xrdp start

#vncpasswd 
mkdir /root/.vnc
wget -O /root/.vnc/passwd http://10.24.4.84/pxe/saltstack/etc/root/.vnc/passwd
#service vncserver start

#########################
# set ntp
#########################
wget -O /etc/sysconfig/ntpdate http://10.24.4.84/pxe/saltstack/etc/sysconfig/ntpdate
wget -O /etc/ntp.conf http://10.24.4.84/pxe/saltstack/etc/ntp.conf
wget -O /etc/ntp/step-tickers http://10.24.4.84/pxe/saltstack/etc/ntp/step-tickers
ntpdate -u ${ntp_server} && hwclock -w
#########################
# set ssh
#########################
wget -O /etc/ssh/sshd_config http://10.24.4.84/pxe/saltstack/etc/ssh/sshd_config
chmod 600 /etc/sysconfig/selinux
service sshd reload
#########################
# set services
#########################
wget -O /etc/sysconfig/selinux http://10.24.4.84/pxe/saltstack/etc/sysconfig/selinux
wget -O /etc/sysconfig/iptables http://10.24.4.84/pxe/saltstack/etc/sysconfig/iptables
chmod 600 /etc/sysconfig/iptables
chmod 600 /etc/sysconfig/selinux
#########################
# set others
#########################
#cmk
#ocsng
#hsflow
#fabric
#hwinfo

#########################
# install xs-tools
#########################
if
  which xe-linux-distribution >/dev/null 2>&1
then
  sed -i '/firstrun/d' /etc/rc.local
  cd / && umount -f ${mnt}
  exit
else
  nfs_server="10.24.4.84"
  exports="/var/www/html/exports"
  mnt="/mnt"
  mount -t nfs ${nfs_server}:${exports} ${mnt}
  echo y | ${mnt}/xstools/Linux/install.sh
fi
sleep 3
echo b > /proc/sysrq-trigger
