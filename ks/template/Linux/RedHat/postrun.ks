%post --log=/tmp/ks-post.log
#!/bin/bash
sed -i '/^id/s/3/5/' /etc/inittab
eject
wget -P /tmp http://10.24.4.84/pxe/ks/linux/centos/6.3/x86_64/firstrun-vm.sh
echo 'sh /tmp/firstrun-vm.sh' >> /etc/rc.local
