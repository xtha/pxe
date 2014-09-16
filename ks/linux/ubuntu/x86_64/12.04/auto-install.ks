lang en_US
langsupport en_US
keyboard us
timezone Asia/Shanghai
text
install
skipx
halt
url --url http://mirrors.sohu.com/ubuntu

rootpw password   # you should replace, and use --iscrypted
auth --useshadow --enablemd5
user --disabled

bootloader --location=mbr
zerombr yes
clearpart --all --initlabel
part /boot --fstype=ext2 --size=64
part swap --size=1024
part / --fstype=ext3 --size=1 --grow

network --device=eth0 --bootproto=static --ip=192.168.111.231 --netmask=255.255.255.0 --nameserver=10.24.4.85 --gateway=192.168.111.254
firewall --disabled

%packages
ubuntu-minimal
openssh-server
screen
curl
wget

%post

# update fstab for the root partition
perl -pi -e 's/(errors=remount-ro)/noatime,nodiratime,$1,barrier=0/' /etc/fstab

# point sh to bash instead of dash
rm /bin/sh
ln -s /bin/bash /bin/sh

# add normal apt source list
(
cat <<'EOP'
deb http://mirrors.sohu.com/ubuntu/ precise main restricted universe
deb http://mirrors.sohu.com/ubuntu/ precise-security main restricted universe
deb http://mirrors.sohu.com/ubuntu/ precise-updates main restricted universe
EOP
) > /etc/apt/sources.list
apt-get update
apt-get upgrade -y

# install some additional packages
apt-get install -y xenstore-utils

# set up xenserver automation scripts
AUTOMATER_REPO=https://raw.github.com/krobertson/xenserver-automater
curl $AUTOMATER_REPO/master/usr/sbin/xe-set-hostname > /usr/sbin/xe-set-hostname
curl $AUTOMATER_REPO/master/usr/sbin/xe-set-network > /usr/sbin/xe-set-network
curl $AUTOMATER_REPO/master/usr/sbin/generate-sshd-keys > /usr/sbin/generate-sshd-keys
curl $AUTOMATER_REPO/master/etc/init/xe-automator.conf > /etc/init/xe-automator.conf
chmod a+x /usr/sbin/xe-set-hostname
chmod a+x /usr/sbin/xe-set-network
chmod a+x /usr/sbin/generate-sshd-keys

# setup locales
locale-gen en_US.UTF-8
update-locale LANG="en_US.UTF-8"
echo 'LANG=en_US.UTF-8' >> /etc/environment
echo 'LC_ALL=en_US.UTF-8' >> /etc/environment

# install xe tools
cd /tmp
wget http://some/url/to/xe-guest-utilities_6.0.0-743_amd64.deb
dpkg -i xe-guest-utilities_6.0.0-743_amd64.deb

# install paravirt kernel image
apt-get install -f -y linux-virtual
dpkg -l | grep generic | grep linux | awk '{print $2}' | xargs apt-get remove -y

# clean up some stuff
rm -f /etc/ssh/ssh_host_*
rm -f /var/cache/apt/archives/*.deb
rm -f /var/cache/apt/*cache.bin
rm -f /var/lib/apt/lists/*_Packages
