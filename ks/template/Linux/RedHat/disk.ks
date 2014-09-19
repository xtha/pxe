zerombr
ignoredisk --only-use=xvda
clearpart --all --drives=xvda  --initlabel
bootloader --location=mbr --driveorder=xvda --append="crashkernel=auto rhgb quiet"
