<?php
  
  header ( "Content-type: text/plain" );
  
  $username = $_SERVER["PHP_AUTH_USER"];
  $password = $_SERVER["PHP_AUTH_PW"];
  
  $index = 0;
  
  function title ( $title ) {
    global $username;
    echo "menu title ".$title;
    echo ( $username ? " for ".$username : "" )."\n";
  }
  
  function label ( $label ) {
    global $index;
    $index++;
    echo "label item".$index."\n";
    echo "  menu label ";
    echo "^".( ( $index < 10 ) ? $index :
               sprintf ( "%c", $index + ord ( 'A' ) - 10 ) )." ";
    echo $label."\n";
  }
  
  function sanboot ( $label, $root_path ) {
    label ( $label );
    echo "  kernel cmd.c32\n";
    echo "  append sanboot ".$root_path."\n";
    echo "\n";
  }
  
  function uriboot ( $label, $uri, $args ) {
    label ( $label );
    echo "  kernel ".$uri."\n";
    if ( $args )
        echo "  append ".$args."\n";
  }
  
  function retry () {
    echo "label failed\n";
    echo "  menu label Authentication Failed\n";
    echo "  menu disable\n";
    uriboot ( "Try again", "boot.php", "" );
  }
  
  function authenticated () {
    global $username;
    global $password;
  
    switch ( "$username:$password" ) {
    case "mcb30:password":
    case "guest:guest":
      return 1;
    default:
      return 0;
    }
  }
  
?>
  
  menu background atlantis.png
  prompt 0
  timeout 100
  allowoptions 0
  menu timeoutrow 29
  menu vshift 2
  menu rows 8
  menu color title  1;36;44   #ff8bc2ff #00000000 std
  menu color unsel  37;44     #ff1069c5 #00000000 std
  menu color sel    7;37;40   #ff000000 #ffff7518 all
  menu color hotkey 1;37;44   #ffffffff #00000000 std
  menu color hotsel 1;7;37;40 #ff000431 #ffff7518 all
