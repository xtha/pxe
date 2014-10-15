#!/bin/bash
sed -i '/initdefault:/s/3/5/' /etc/inittab
echo 'PATH=/sbin:/usr/sbin:/usr/sbin:$PATH' >> /root/.bashrc
eject
