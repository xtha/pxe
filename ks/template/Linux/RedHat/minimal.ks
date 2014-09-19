# 必须按照顺序写配置，%pre不能置于前面，获取install.img后才会执行%pre脚本
lang en_US.UTF-8
keyboard us
url --url=http://10.24.4.4/os/linux/centos/x86_64/6.3
text
install
timezone --utc Asia/Shanghai
reboot

%include /tmp/security.ks
%include /tmp/password.ks
%include /tmp/disk.ks
%include /tmp/lvm.ks
%include /tmp/pkg-minimal.ks

%pre --interpreter /usr/bin/python
import socket
import os

print "Hostname"
print socket.gethostbyaddr( os.popen("ifconfig").readlines()[1].split()[1][5:])[0][0];
ipaddr = os.popen("ifconfig").readlines()[1].split()[1][5:]
hostname = socket.gethostbyaddr(ipaddr)[0]
host = hostname.split('.')[0]

f = file("/tmp/network","w")
if os.path.exists ("/proc/sys/net/ipv4/conf/eth0"):
	f.write ("network --bootproto=dhcp --device=eth0\n")
else:	
	f.write ("network --bootproto=dhcp --device=eth1\n")
f.close

url = 'wget http://10.24.4.97/pxe/ks/template/linux/RedHat'

# Get config files for machine.configfilename
for file in ['disk','lvm','security','password', 'pkg-minimal']:
	print("%s/%s.ks -O /tmp/%s.ks" % (url,file,file))
	os.popen("%s/%s.ks -O /tmp/%s.ks" % (url,file,file)).readlines()
	# Otherwise get default file
#	if not os.path.exists ("/tmp/%s.ks" % file):
#		print("%s/%s/%s.%s -O /tmp/%s" % (url,file,file,"default",file))
#		os.popen("%s/%s/%s.%s -O /tmp/%s" % (url,file,file,"default",file)).readlines()
%end
