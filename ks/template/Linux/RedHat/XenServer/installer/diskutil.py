# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN CLEAN INSTALLER
# Disk discovery and utilities
#
# written by Andrew Peace

import re, sys
import os.path
import constants
import CDROM
import fcntl
import util
import netutil
from util import dev_null
import xelogging
from disktools import *
import time
from snackutil import ButtonChoiceWindowEx

use_mpath = False

def mpath_cli_is_working():
    regex = re.compile("switchgroup")
    try:
        (rc,stdout) = util.runCmd2(["multipathd","-k"], with_stdout=True, inputtext="help")
        m=regex.search(stdout)
        if m:
            return True
        else:
            return False
    except:
        return False

def wait_for_multipathd():
    for i in range(0,120):
        if mpath_cli_is_working():
            return
        time.sleep(1)
    msg = "Unable to contact Multipathd daemon"
    xelogging.log(msg)
    raise Exception(msg)

# CA-58939: create udev rule to enslave paths which come up after multipathd has started
#           this needs to be run before 50-udev.rules so that by the time the symlink 
#           is created the new path is already enslaved to a master
rules = '/etc/udev/rules.d/45-multipath.rules'
def add_mpath_udev_rule():
    fd = open(rules,'w')
    rule = "ACTION==\"add\", RUN+=\"/bin/bash -c 'echo add path %k | /sbin/multipathd -k > /dev/null'\""
    fd.write(rule)
    fd.close()
    
def del_mpath_udev_rule():
    os.unlink(rules)

def mpath_enable():
    global use_mpath
    assert 0 == util.runCmd2(['modprobe','dm-multipath'])

    # This creates maps for all disks at start of day (because -e is ommitted)
    assert 0 == util.runCmd2('multipathd -d &> /var/log/multipathd &')
    wait_for_multipathd()
    # CA-48440: Cope with lost udev events
    add_mpath_udev_rule()
    util.runCmd2(["multipathd","-k"], inputtext="reconfigure")

    # Tell DM to create partition nodes for newly created mpath devices
    assert 0 == createMpathPartnodes()
    xelogging.log("created multipath device(s)");
    use_mpath = True

def mpath_disable():
    destroyMpathPartnodes()
    util.runCmd2(['killall','multipathd'])
    del_mpath_udev_rule()
    util.runCmd2(['/sbin/multipath','-F'])
    use_mpath = False

# hd* -> (ide has majors 3, 22, 33, 34, 56, 57, 88, 89, 90, 91, each major has
# two disks, with minors 0... and 64...)
ide_majors = [ 3, 22, 33, 34, 56, 57, 88, 89, 90, 91 ]
disk_nodes  = [ (x, 0) for x in ide_majors ]
disk_nodes += [ (x, 64) for x in ide_majors ]

# sd* -> (sd-mod has majors 8, 65 ... 71: each device has eight minors, each 
# major has sixteen disks).
disk_nodes += [ (8, x * 16) for x in range(16) ]
disk_nodes += [ (65, x * 16) for x in range(16) ]
disk_nodes += [ (66, x * 16) for x in range(16) ]
disk_nodes += [ (67, x * 16) for x in range(16) ]
disk_nodes += [ (68, x * 16) for x in range(16) ]
disk_nodes += [ (69, x * 16) for x in range(16) ]
disk_nodes += [ (70, x * 16) for x in range(16) ]
disk_nodes += [ (71, x * 16) for x in range(16) ]

# xvd* -> (blkfront has major 202: each device has 15 minors)
disk_nodes += [ (202, x * 16) for x in range(16) ]

# /dev/cciss : c[0-7]d[0-15]: Compaq Next Generation Drive Array
# /dev/ida   : c[0-7]d[0-15]: Compaq Intelligent Drive Array
for major in range(72, 80) + range(104, 112):
    disk_nodes += [ (major, x * 16) for x in range(16) ]

# /dev/rd    : c[0-7]d[0-31]: Mylex DAC960 PCI RAID controller
for major in range(48, 56):
    disk_nodes += [ (major, x * 8) for x in range(32) ]

def getDiskList():
    # read the partition tables:
    parts = open("/proc/partitions")
    partlines = map(lambda x: re.sub(" +", " ", x).strip(),
                    parts.readlines())
    parts.close()

    # parse it:
    disks = []
    for l in partlines:
        try:
            (major, minor, size, name) = l.split(" ")
            (major, minor, size) = (int(major), int(minor), int(size))
            if (major, minor) in disk_nodes:
                if major == 202 and isRemovable("/dev/" + name): # Ignore PV CDROM devices
                    continue
                if hasDeviceMapperHolder("/dev/" + name.replace("!","/")):
                    # skip device that cannot be used
                    continue
                disks.append(name.replace("!", "/"))
        except:
            # it wasn't an actual entry, maybe the headers or something:
            continue
    # Add multipath nodes to list
    disks.extend(map(lambda node: node.replace('/dev/',''), getMpathNodes()))

    return disks

def getPartitionList():
    disks = getDiskList()
    rv  = []
    for disk in disks:
        if isDeviceMapperNode('/dev/' + disk):
            name = disk.split('/',1)[1]
            partitions = filter(lambda s: s.startswith("%sp" % name), os.listdir('/dev/mapper/'))
            partitions = map(lambda s: "mapper/%s" % s, partitions)
        else:
            name = disk.replace("/", "!")
            partitions = filter(lambda s: s.startswith(name), os.listdir('/sys/block/%s' % name))
            partitions = map(lambda n: n.replace("!","/"), partitions)
        rv.extend(partitions)
    return rv

def partitionsOnDisk(dev):
    if dev.startswith('/dev/'):
        dev = dev[5:]
    dev = dev.replace('/', '!')
    return filter(lambda x: x.startswith(dev),
                  os.listdir(os.path.join('/sys/block', dev)))

def getQualifiedDiskList():
    return map(lambda x: getQualifiedDeviceName(x), getDiskList())

def getQualifiedPartitionList():
    return [getQualifiedDeviceName(x) for x in getPartitionList()]

def getRemovableDeviceList():
    devs = os.listdir('/sys/block')
    removable_devs = []
    for d in devs:
        if isRemovable(d):
            removable_devs.append(d.replace("!", "/"))

    return removable_devs

def removable(device):
    if device.startswith('/dev/'):
        device = device[5:]

    # CA-25624 - udev maps sr* to scd*
    if device.startswith('scd'):
        device = 'sr'+device[3:]

    return device in getRemovableDeviceList()

def getQualifiedDeviceName(disk):
    return "/dev/%s" % disk

# Given a partition (e.g. /dev/sda1), get the id symlink:
def idFromPartition(partition):
    symlink = None
    v, out = util.runCmd2(['/usr/bin/udevinfo', '-q', 'symlink', '-n', partition], with_stdout = True)
    if v == 0:
        for link in out.split():
            if link.startswith('disk/by-id') and not link.startswith('disk/by-id/edd'):
                symlink = '/dev/'+link
                break
    return symlink

# Given a id symlink (e.g. /dev/disk/by-id/scsi-...), get the device
def partitionFromId(symlink):
    return os.path.realpath(symlink)

def __readOneLineFile__(filename):
    try:
        f = open(filename)
        value = f.readline()
        f.close()
        return value
    except Exception, e:
        raise e

def getDiskDeviceVendor(dev):

    # For Multipath nodes return info about 1st slave
    if not dev.startswith("/dev/"):
        dev = '/dev/' + dev
    if isDeviceMapperNode(dev):
        return getDiskDeviceVendor(getMpathSlaves(dev)[0])

    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/vendor" % dev):
        return __readOneLineFile__("/sys/block/%s/device/vendor" % dev).strip(' \n')
    else:
        return ""

def getDiskDeviceModel(dev):

    # For Multipath nodes return info about 1st slave
    if not dev.startswith("/dev/"):
        dev = '/dev/' + dev
    if isDeviceMapperNode(dev):
        return getDiskDeviceModel(getMpathSlaves(dev)[0])

    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/model" % dev):
        return __readOneLineFile__("/sys/block/%s/device/model" % dev).strip('  \n')
    else:
        return ""
    
def getDiskDeviceSize(dev):

    # For Multipath nodes return info about 1st slave
    if not dev.startswith("/dev/"):
        dev = '/dev/' + dev
    if isDeviceMapperNode(dev):
        return getDiskDeviceSize(getMpathSlaves(dev)[0])

    if dev.startswith("/dev/"):
        dev = re.match("/dev/(.*)", dev).group(1)
    dev = dev.replace("/", "!")
    if os.path.exists("/sys/block/%s/device/block/size" % dev):
        return int(__readOneLineFile__("/sys/block/%s/device/block/size" % dev))
    elif os.path.exists("/sys/block/%s/size" % dev):
        return int(__readOneLineFile__("/sys/block/%s/size" % dev))

def getDiskSerialNumber(dev):
    # For Multipath nodes return info about 1st slave
    if not dev.startswith("/dev/"):
        dev = '/dev/' + dev
    if isDeviceMapperNode(dev):
        return getDiskSerialNumber(getMpathSlaves(dev)[0])

    rc, out = util.runCmd2(['/bin/sdparm', '-q', '-i', '-p', 'sn', dev], with_stdout = True)
    if rc == 0:
        lines = out.split('\n')
        if len(lines) >= 2:
            return lines[1].strip()
    return ""

def isRemovable(path):

    if path.startswith('/dev/mapper') or path.startswith('/dev/dm-') or path.startswith('dm-'):
        return False 

    if path.startswith("/dev/"):
        dev = re.match("/dev/(.*)", path).group(1)
    else:
        dev = path
        
    dev = dev.replace("/", "!")

    if dev.startswith("xvd"):
        is_cdrom = False
        f = None
        try:
            f = open(path, 'r')
            if fcntl.ioctl(f, CDROM.CDROM_GET_CAPABILITY) == 0:
                is_cdrom = True
        except: # Any exception implies this is not a CDROM
            pass

        if f is not None:
            f.close()

        if is_cdrom:
            return True

    if os.path.exists("/sys/block/%s/removable" % dev):
        return int(__readOneLineFile__("/sys/block/%s/removable" % dev)) == 1
    else:
        return False

def blockSizeToGBSize(blocks):
    return (long(blocks) * 512) / (1024 * 1024 * 1024)

def blockSizeToMBSize(blocks):
    return (long(blocks) * 512) / (1024 * 1024)
    
def getHumanDiskSize(blocks):
    gb = blockSizeToGBSize(blocks)
    if gb > 0:
        return "%d GB" % gb
    else:
        return "%d MB" % blockSizeToMBSize(blocks)

def getExtendedDiskInfo(disk, inMb = 0):
    return (getDiskDeviceVendor(disk), getDiskDeviceModel(disk),
            inMb and (getDiskDeviceSize(disk)/2048) or getDiskDeviceSize(disk))


def readExtPartitionLabel(partition):
    """Read the ext partition label."""
    rc, out = util.runCmd2(['/sbin/e2label', partition], with_stdout = True)
    if rc == 0:
        label = out.strip()
    else:
        raise Exception("%s is not ext partition" % partition)
    return label

def getHumanDiskName(disk):

    # For Multipath nodes return info about 1st slave
    if not disk.startswith("/dev/"):
        disk = '/dev/' + disk
    if isDeviceMapperNode(disk):
        return getHumanDiskName(getMpathSlaves(disk)[0])

    if disk.startswith('/dev/disk/by-id/'):
        return disk[16:]
    if disk.startswith('/dev/'):
        return disk[5:]
    return disk

# given a list of disks, work out which ones are part of volume
# groups that will cause a problem if we install XE to those disks:
def findProblematicVGs(disks):
    real_disks = map(lambda d: os.path.realpath(d), disks)

    # which disks are the volume groups on?
    vgdiskmap = {}
    tool = LVMTool()
    for pv in tool.pvs:
        if pv['vg_name'] not in vgdiskmap: vgdiskmap[pv['vg_name']] = []
        try:
            device = diskDevice(pv['pv_name'])
        except:
            # CA-35020: whole disk
            device = pv['pv_name']
        vgdiskmap[pv['vg_name']].append(device)

    # for each VG, map the disk list to a boolean list saying whether that
    # disk is in the set we're installing to:
    vgusedmap = {}
    for vg in vgdiskmap:
        vgusedmap[vg] = [disk in real_disks for disk in vgdiskmap[vg]]

    # now, a VG is problematic if it its vgusedmap entry contains a mixture
    # of True and False.  If it's entirely True or entirely False, that's OK:
    problems = []
    for vg in vgusedmap:
        p = False
        for x in vgusedmap[vg]:
            if x != vgusedmap[vg][0]:
                p = True
        if p:
            problems.append(vg)

    return problems

def log_available_disks():
    disks = getQualifiedDiskList()

    # make sure we have discovered at least one disk and
    # at least one network interface:
    if len(disks) == 0:
        xelogging.log("No disks found on this host.")
    else:
        # make sure that we have enough disk space:
        xelogging.log("Found disks: %s" % str(disks))
        diskSizes = [getDiskDeviceSize(x) for x in disks]
        diskSizesGB = [blockSizeToGBSize(x) for x in diskSizes]
        xelogging.log("Disk sizes: %s" % str(diskSizesGB))

        dom0disks = filter(lambda x: constants.min_primary_disk_size <= x,
                           diskSizesGB)
        if len(dom0disks) == 0:
            xelogging.log("Unable to find a suitable disk (with a size greater than %dGB) to install to." % constants.min_primary_disk_size)

INSTALL_RETAIL = 1
STORAGE_LVM = 1
STORAGE_EXT3 = 2

def probeDisk(device, justInstall = False):
    """Examines device and reports the apparent presence of a XenServer installation and/or related usage
    Returns a tuple (boot, state, storage)
    
    Where:
    
    	boot is a tuple of None, INSTALL_RETAIL and the partition device
        state is a tuple of True or False and the partition device
        storage is a tuple of None, STORAGE_LVM or STORAGE_EXT3 and the partition device
    """

    boot = (None, None)
    state = (False, None)
    storage = (None, None)
    possible_srs = []
        
    tool = PartitionTool(device)
    for num, part in tool.iteritems():
        label = None
        part_device = tool._partitionDevice(num)

        if part['id'] == tool.ID_LINUX:
            try:
                label = readExtPartitionLabel(part_device)
            except:
                pass

        if part['active']:
            if part['id'] == tool.ID_LINUX:
                # probe for retail
                if label and label.startswith('root-'):
                    boot = (INSTALL_RETAIL, part_device)
                    state = (True, part_device)
                    if tool.partitions.has_key(num+2):
                        # George Retail and earlier didn't use the correct id for SRs
                        possible_srs = [num+2]
        else:
            if part['id'] == tool.ID_LINUX_LVM:
                if num not in possible_srs:
                    possible_srs.append(num)

    if not justInstall:
        lv_tool = len(possible_srs) and LVMTool()
        for num in possible_srs:
            part_device = tool._partitionDevice(num)

            if lv_tool.isPartitionConfig(part_device):
                state = (True, part_device)
            elif lv_tool.isPartitionSR(part_device):
                pv = lv_tool.deviceToPVOrNone(part_device)
                if pv is not None and pv['vg_name'].startswith(lv_tool.VG_EXT_SR_PREFIX):
                    # odd 'ext3 in an LV' SR
                    storage = (STORAGE_EXT3, part_device)
                else:
                    storage = (STORAGE_LVM, part_device)
    
    xelogging.log('Probe of '+device+' found boot='+str(boot)+' state='+str(state)+' storage='+str(storage))

    return (boot, state, storage)


class IscsiDeviceException(Exception):
    pass

# Keep track of iscsi disks we have logged into
iscsi_disks = []

# Return True if this is an iscsi device that we have previously logged into
def is_iscsi(device):

    # If this is a multipath device check whether the first slave is iSCSI
    if use_mpath:
        slaves = getMpathSlaves(device)
        if slaves:
            device = slaves[0]        
    
    major, minor = getMajMin(device)
    
    for d in iscsi_disks:
        try:
            if (major,minor) == getMajMin(d):
                return True
        except:
            pass

    return False

def iscsi_get_sid(targetip, iqn):
    "Get the Session ID corresponding to an IQN to which we are logged in"
    rv, out = util.runCmd2([ 'iscsiadm', '-m', 'session' ], with_stdout=True)
    assert(rv == 0)
    lines = out.strip().split('\n')
    regex = re.compile('^tcp: \\[(\\d+)\\] ([^:]+):([^,]+),[^ ]+ (.*)$')
    tuples = map(lambda line: regex.match(line).groups(), lines)
    tuples = filter(lambda entry: entry[1] == targetip and entry[3] == iqn, tuples)
    assert(len(tuples) == 1)
    sid = int(tuples[0][0])
    return sid

def rfc4173_to_disk(rfc4173_spec):
    "Get the disk (e.g. '/dev/sdb') corresponding to a LUN on an IQN to which we are logged in"
    try:
        parts = rfc4173_spec.split(':',5)
        assert(parts[0] == "iscsi")
        targetip = parts[1]
        lun = parts[4] and int(parts[4]) or 0        
        iqn = parts[5]
    except:
        raise IscsiDeviceException, "Cannot parse spec %s" % rfc4173_spec
    
    sid = iscsi_get_sid(targetip, iqn)
    rv, out = util.runCmd2([ 'iscsiadm', '-m', 'session', '-r', str(sid), '-P', '3' ], with_stdout=True)
    assert(rv == 0)
    lines = out.strip().split('\n')
    regex = re.compile('^\\s*\\w+ Channel \\d+ Id \\d+ Lun: %d$' % lun)
    while lines:
        line = lines.pop(0)
        if regex.match(line):
            # next line says what the disk is called!
            line = lines.pop(0)
            regex2 = re.compile('^\\s*Attached scsi disk (\\w+)\\s+.*$')
            match = regex2.match(line)
            assert match != None
            return '/dev/' + match.groups()[0]
    raise Exception, "Could not find iscsi disk with IQN %s and lun %d" % (iqn,lun)
            

def attach_rfc4173(iname, rfc4173_spec):
    """ Attach a disk given an initiator name, and spec in the following format:
     "iscsi:"<targetip>":"<protocol>":"<port>":"<LUN>":"<targetname>

     return disk, e.g. "/dev/sdb"
    """
    try:
        parts = rfc4173_spec.split(':',5)
        assert(parts[0] == "iscsi")
        targetip = parts[1]
        port = parts[3]
        lun = parts[4] and int(parts[4]) or 0        
        iqn = parts[5]
    except:
        raise IscsiDeviceException, "Cannot parse spec %s" % rfc4173_spec
    
    if port:
        targetip += ':%s' % port

    # Attach to disk
    if not os.path.exists("/etc/iscsi/initiatorname.iscsi"):
        rv, iname = util.runCmd2([ '/sbin/iscsi-iname' ], with_stdout=True)
        if rv:
            raise RuntimeError, "/sbin/iscsi-iname failed"
        open("/etc/iscsi/initiatorname.iscsi","w").write("InitiatorName=%s"  % iname)

    rv = util.runCmd2([ '/sbin/modprobe', 'iscsi_tcp' ])
    if rv:
        raise RuntimeError, "/sbin/modprobe iscsi_tcp failed"
    try:
        if not util.pidof('iscsid'):
            fd = open("/etc/iscsi/initiatorname.iscsi", "w")
            fd.write("InitiatorName=%s" % iname)
            fd.close()
            rv = util.runCmd2([ '/sbin/iscsid' ])          # start iscsiadm
            if rv:
                raise RuntimeError, "/sbin/iscsid failed"
        rv = util.runCmd2([ '/sbin/iscsiadm', '-m', 'discovery', '-t', 'sendtargets', '-p', targetip])
        if rv: 
            raise RuntimeError, "/sbin/iscsiadm -m discovery failed"
        rv = util.runCmd2([ '/sbin/iscsiadm', '-m', 'node', '-T', iqn, '-p', targetip, '-l']) # login
        if rv:
            raise RuntimeError, "/sbin/iscsiadm -m node -l failed"
    finally:
        util.runCmd2([ '/sbin/udevsettle' ])           # update /dev

    disk = rfc4173_to_disk(rfc4173_spec)
    iscsi_disks.append(disk)

    return disk


class Struct:
    def __init__(self, *inArgs, **inKeywords):
        for k, v in inKeywords.items():
            setattr(self, k, v)

sysfs_ibft_dir = "/sys/firmware/ibft"
def have_ibft():
    """ Determine if an iBFT is present """
    rv = util.runCmd2([ '/sbin/modprobe', 'iscsi_ibft' ])
    if rv:
        raise RuntimeError, "/sbin/modprobe iscsi_ibft failed"
    if os.path.isdir("%s/initiator" % sysfs_ibft_dir):
        xelogging.log("process_ibft: iBFT found.")
        return True
    xelogging.log("process_ibft: No iBFT found.")
    return False
    

def read_ibft():
    """ Read in the iBFT (iSCSI Boot Firmware Table) from /sys/firmware/ibft/
    and return an initiator name and a list of target configs.
    """

    flags = int(open("%s/initiator/flags" % sysfs_ibft_dir).read())
    if (flags & 3) != 3:
        xelogging.log("process_ibft: Initiator block in iBFT not valid or not selected.")
        return
    try:
        iname = open("%s/initiator/initiator-name" % sysfs_ibft_dir).read()
    except:
        raise RuntimeError, "No initiator name in iBFT"

    targets = [ d for d in os.listdir(sysfs_ibft_dir) if d.startswith("target") ]
    netdevs = [ (d, open('/sys/class/net/%s/address' % d).read().strip()) 
                for d in os.listdir('/sys/class/net') 
                if d.startswith('eth') ]
    target_configs = []
    for d in targets:
        flags = int(open("%s/%s/flags" % (sysfs_ibft_dir,d)).read())
        if (flags & 3) != 3:
            xelogging.log("process_ibft: %s block in iBFT not valid or not selected." %d)
            continue

        # Find out details of target
        tgtip = open("%s/%s/ip-addr" % (sysfs_ibft_dir,d)).read().strip()
        lun = open("%s/%s/lun" % (sysfs_ibft_dir,d)).read().strip()
        lun = reduce(lambda total,i: (total*10)+int(lun[7-i]), range(8))
        nicid = open("%s/%s/nic-assoc" % (sysfs_ibft_dir,d)).read().strip()
        nicid = int(nicid)
        port = open("%s/%s/port" % (sysfs_ibft_dir,d)).read().strip()
        port = int(port)
        iqn = open("%s/%s/target-name" % (sysfs_ibft_dir,d)).read().strip()
            
        # Find out details of NIC used with this target
        hwaddr = open("%s/ethernet%d/mac" % (sysfs_ibft_dir,nicid)).read().strip()
        ip = open("%s/ethernet%d/ip-addr" % (sysfs_ibft_dir,nicid)).read().strip()
        if not os.path.isfile("%s/ethernet%d/gateway" % (sysfs_ibft_dir,nicid)):
            gw = None
        else:
            gw = open("%s/ethernet%d/gateway" % (sysfs_ibft_dir,nicid)).read().strip()
        nm = open("%s/ethernet%d/subnet-mask" % (sysfs_ibft_dir,nicid)).read().strip()
        flags = int(open("%s/ethernet%d/flags" % (sysfs_ibft_dir,nicid)).read())
        assert (flags & 3) == 3
            
        mac = open('%s/ethernet%d/mac' % (sysfs_ibft_dir,nicid)).read().strip()
        try:
            iface = filter(lambda pair: pair[1] == mac, netdevs)[0][0]
        except:
            raise RuntimeError, "Found mac %s in iBFT but cannot find matching NIC"

        target_configs.append(Struct(iface=iface, ip=ip, nm=nm, gw=gw, 
                                     tgtip=tgtip, port=port, lun=lun, iqn=iqn))
    return iname, target_configs


ibft_reserved_nics = []
def process_ibft(ui, interactive):
    """ Bring up any disks that the iBFT should be attached, and reserve the NICs that
    it says should be used for iSCSI
    """
    
    if not have_ibft():
        return

    try: 
        iname, target_configs = read_ibft()
    except:
        # only raise exception if user decides to proceed
        if ui and interactive:
            msg = "Found iSCSI Boot Firmware Table\n\nAttach to disks specified in iBFT?"
            button = ButtonChoiceWindowEx(ui.screen, "Attach iSCSI disks" , msg, ['Yes', 'No'])
            if button == 'no':
                return
        raise
    else:
        # Do nothing if the iBFT contains no valid targets
        if len(target_configs) == 0:
            xelogging.log("process_ibft: No valid target configs found in iBFT")
            return
        
        # If interactive, ask user if he wants to proceed
        if ui and interactive:
            nics = list(set([ conf.iface for conf in target_configs ]))
            nics.sort()
            msg = \
                "Found iSCSI Boot Firmware Table\n\nAttach to disks specified in iBFT?\n\n" \
                "This will reserve %s for iSCSI disk access.  Reserved NICs are not available " \
                "for use as the management interface or for use by virtual machines."  % " and ".join(nics)
            button = ButtonChoiceWindowEx(ui.screen, "Attach iSCSI disks" , msg, ['Yes', 'No'], width=60)
            if button == 'no':
                return
    
    # Bring up the targets
    for conf in target_configs:
        # Bring up interface
        if conf.iface not in ibft_reserved_nics:
            rv = util.runCmd2(['ifconfig', conf.iface, conf.ip, 'netmask', conf.nm])
            assert rv == 0
            ibft_reserved_nics.append(conf.iface)
            xelogging.log("process_ibft: reserving %s for access to iSCSI disk" % conf.iface)
            
        # Pin tgtip to this interface
        if netutil.network(conf.ip, conf.nm) == netutil.network(conf.tgtip, conf.nm):
            rv = util.runCmd2(['ip', 'route', 'add', conf.tgtip, 'dev', conf.iface])
        else:
            assert conf.gw
            rv = util.runCmd2(['ip', 'route', 'add', conf.tgtip, 'dev', conf.iface, 'via', conf.gw])

        # Attach to target (this creates new nodes /dev)
        spec = "iscsi:%s::%d:%d:%s" % (conf.tgtip, conf.port, conf.lun, conf.iqn)
        try:
            disk = attach_rfc4173(iname, spec)
        except:
            raise RuntimeError, "Could not attach to iSCSI LUN %s" % spec
        xelogging.log("process_ibft: attached iSCSI disk %s." % disk)

def release_ibft_disks():
    if util.pidof('iscsid'):
        util.runCmd2([ '/sbin/iscsiadm', '-m', 'session', '-u'])
        util.runCmd2([ '/sbin/iscsiadm', '-k', '0'])
        iscsi_disks = []
