lang en_US.UTF-8
keyboard us
url --url=http://192.168.31.245/os/Linux/RedHat/RedHat/x86_64/6.3
text
install
bootloader --location=mbr --driveorder=xvda --append=" rhgb crashkernel=auto quiet"
timezone --utc Asia/Shanghai
reboot

%include /tmp/security.ks
%include /tmp/password.ks
%include /tmp/disk.ks
%include /tmp/lvm-32g.ks
%include /tmp/pkg-mini-desktop.ks
%include /tmp/postrun.ks

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

url = 'wget http://192.168.11.8/pxe/ks/template/Linux/RedHat'

# Get config files for machine.configfilename
for file in ['postrun', disk', 'lvm-32g', 'postrun', 'security','password', 'pkg-mini-desktop']:
	print("%s/%s.ks -O /tmp/%s.ks" % (url,file,file))
	os.popen("%s/%s.ks -O /tmp/%s.ks" % (url,file,file)).readlines()
	# Otherwise get default file
#	if not os.path.exists ("/tmp/%s.ks" % file):
#		print("%s/%s/%s.%s -O /tmp/%s" % (url,file,file,"default",file))
#		os.popen("%s/%s/%s.%s -O /tmp/%s" % (url,file,file,"default",file)).readlines()
%end
%post
#!/bin/bash
sh /tmp/postrun.sh
