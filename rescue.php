<?PHP
foreach($_GET as $k=>$v) $$k=$v;
echo "#!gpxe
set 209:string pxelinux.cfg/default
set 210:string http://pxe.hdtr.com/pxe/
chain \${210:string}pxelinux.0 ||
chain http://boot.ipxe.org/demo/boot.php ||
shell
";
?>
