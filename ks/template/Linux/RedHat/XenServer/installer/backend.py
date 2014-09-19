# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN CLEAN INSTALLER
# Functions to perform the XE installation
#
# written by Andrew Peace

import os
import os.path
import subprocess
import datetime
import re
import tempfile

import repository
import generalui
import xelogging
import util
import diskutil
from disktools import *
import netutil
import shutil
import constants
import hardware
import upgrade
import init_constants
import scripts
import xcp.bootloader as bootloader
import netinterface
import tui.repo

# Product version and constants:
import version
from version import *
from constants import *

MY_PRODUCT_BRAND = PRODUCT_BRAND or PLATFORM_NAME
MY_PRODUCT_VERSION = PRODUCT_VERSION or PLATFORM_VERSION

class InvalidInstallerConfiguration(Exception):
    pass

################################################################################
# FIRST STAGE INSTALLATION:

class Task:
    """
    Represents an install step.
    'fn'   is the function to execute
    'args' is a list of value labels identifying arguments to the function,
    'returns' is a list of the labels of the return values, or a function
           that, when given the 'args' labels list, returns the list of the
           labels of the return values.
    """

    def __init__(self, fn, args, returns, args_sensitive = False,
                 progress_scale = 1, pass_progress_callback = False,
                 progress_text = None):
        self.fn = fn
        self.args = args
        self.returns = returns
        self.args_sensitive = args_sensitive
        self.progress_scale = progress_scale
        self.pass_progress_callback = pass_progress_callback
        self.progress_text = progress_text

    def execute(self, answers, progress_callback = lambda x: ()):
        args = self.args(answers)
        assert type(args) == list

        if not self.args_sensitive:
            xelogging.log("TASK: Evaluating %s%s" % (self.fn, args))
        else:
            xelogging.log("TASK: Evaluating %s (sensitive data in arguments: not logging)" % self.fn)

        if self.pass_progress_callback:
            args.insert(0, progress_callback)

        rv = apply(self.fn, args)
        if type(rv) is not tuple:
            rv = (rv,)
        myrv = {}

        if callable(self.returns):
            ret = apply(self.returns, args)
        else:
            ret = self.returns
            
        for r in range(len(ret)):
            myrv[ret[r]] = rv[r]
        return myrv

###
# INSTALL SEQUENCES:
# convenience functions
# A: For each label in params, gives an arg function that evaluates
#    the labels when the function is called (late-binding)
# As: As above but evaluated immediately (early-binding)
# Use A when you require state values as well as the initial input values
A = lambda ans, *params: ( lambda a: [a.get(param) for param in params] )
As = lambda ans, *params: ( lambda _: [ans.get(param) for param in params] )

def getPrepSequence(ans, interactive):
    seq = [ 
        Task(util.getUUID, As(ans), ['installation-uuid']),
        Task(util.getUUID, As(ans), ['control-domain-uuid']),
        Task(inspectTargetDisk, A(ans, 'primary-disk', 'installation-to-overwrite', 'initial-partitions', 'zap-utility-partitions', 'preserve-first-partition'), ['primary-partnum', 'backup-partnum', 'storage-partnum']),
        Task(selectPartitionTableType, A(ans, 'primary-disk', 'install-type', 'primary-partnum'), ['partition-table-type']),
        ]
    if ans['install-type'] == INSTALL_TYPE_FRESH:
        seq += [
            Task(removeBlockingVGs, As(ans, 'guest-disks'), []),
            Task(writeDom0DiskPartitions, A(ans, 'primary-disk', 'primary-partnum', 'backup-partnum', 'storage-partnum', 'sr-at-end', 'partition-table-type'), []),
            ]
        seq.append(Task(writeGuestDiskPartitions, A(ans,'primary-disk', 'guest-disks', 'partition-table-type'), []))
    elif ans['install-type'] == INSTALL_TYPE_REINSTALL:
        if not interactive:
            seq.append(Task(verifyRepo, A(ans, 'source-media', 'source-address', 'ui'), []))
        seq.append(Task(getUpgrader, A(ans, 'installation-to-overwrite'), ['upgrader']))
        seq.append(Task(prepareTarget,
                        lambda a: [ a['upgrader'] ] + [ a[x] for x in a['upgrader'].prepTargetArgs ],
                        lambda progress_callback, upgrader, *a: upgrader.prepTargetStateChanges,
                        progress_text = "Preparing target disk...",
                        progress_scale = 100,
                        pass_progress_callback = True))
        if ans.has_key('backup-existing-installation') and ans['backup-existing-installation']:
            seq.append(Task(doBackup,
                            lambda a: [ a['upgrader'] ] + [ a[x] for x in a['upgrader'].doBackupArgs ],
                            lambda progress_callback, upgrader, *a: upgrader.doBackupStateChanges,
                            progress_text = "Backing up existing installation...",
                            progress_scale = 100,
                            pass_progress_callback = True))
        seq.append(Task(prepareUpgrade,
                        lambda a: [ a['upgrader'] ] + [ a[x] for x in a['upgrader'].prepUpgradeArgs ],
                        lambda progress_callback, upgrader, *a: upgrader.prepStateChanges,
                        progress_text = "Preparing for upgrade...",
                        progress_scale = 100,
                        pass_progress_callback = True))
    seq += [
        Task(createDom0DiskFilesystems, A(ans, 'primary-disk', 'primary-partnum'), []),
        Task(mountVolumes, A(ans, 'primary-disk', 'primary-partnum', 'cleanup'), ['mounts', 'cleanup']),
        ]
    return seq

def getRepoSequence(ans, repos):
    seq = []
    for repo in repos:
        seq.append(Task(checkRepoDeps, (lambda myr: lambda a: [myr, a['installed-repos'], a['branding']])(repo), ['branding']))
        seq.append(Task(repo.accessor().start, lambda x: [], []))
        for package in repo:
            seq += [
                # have to bind package at the current value, hence the myp nonsense:
                Task(installPackage, (lambda myp: lambda a: [a['mounts'], myp])(package), [],
                     progress_scale = (package.size / 100),
                     pass_progress_callback = True,
                     progress_text = "Installing from %s..." % repo.name())
                ]
        seq.append(Task(repo.record_install, A(ans, 'mounts', 'installed-repos'), ['installed-repos']))
        seq.append(Task(repo.accessor().finish, lambda x: [], []))
    return seq

def getFinalisationSequence(ans):
    seq = [
        Task(installBootLoader, A(ans, 'mounts', 'primary-disk', 'partition-table-type', 'primary-partnum', 'serial-console', 'boot-serial', 'xen-cpuid-masks', 'bootloader-location'), []),
        Task(doDepmod, A(ans, 'mounts'), []),
        Task(writeResolvConf, A(ans, 'mounts', 'manual-hostname', 'manual-nameservers'), []),
        Task(writeKeyboardConfiguration, A(ans, 'mounts', 'keymap'), []),
        Task(writeModprobeConf, A(ans, 'mounts'), []),
        Task(configureNetworking, A(ans, 'mounts', 'net-admin-interface', 'net-admin-bridge', 'net-admin-configuration', 'manual-hostname', 'manual-nameservers', 'network-hardware', 'preserve-settings', 'network-backend'), []),
        Task(prepareSwapfile, A(ans, 'mounts'), []),
        Task(writeFstab, A(ans, 'mounts'), []),
        Task(enableAgent, A(ans, 'mounts', 'network-backend'), []),
        Task(mkinitrd, A(ans, 'mounts', 'primary-disk', 'primary-partnum'), []),
        Task(configureKdump, A(ans, 'mounts'), []),
        Task(writeInventory, A(ans, 'installation-uuid', 'control-domain-uuid', 'mounts', 'primary-disk', 'backup-partnum', 'storage-partnum', 'guest-disks', 'net-admin-bridge', 'branding'), []),
        Task(touchSshAuthorizedKeys, A(ans, 'mounts'), []),
        Task(setRootPassword, A(ans, 'mounts', 'root-password'), [], args_sensitive = True),
        Task(setTimeZone, A(ans, 'mounts', 'timezone'), []),
        ]

    # on fresh installs, prepare the storage repository as required:
    if ans['install-type'] == INSTALL_TYPE_FRESH:
        seq += [
            Task(prepareStorageRepositories, A(ans, 'mounts', 'primary-disk', 'storage-partnum', 'guest-disks', 'sr-type'), []),
            Task(configureSRMultipathing, A(ans, 'mounts', 'primary-disk'), []),
            ]
    if ans['time-config-method'] == 'ntp':
        seq.append( Task(configureNTP, A(ans, 'mounts', 'ntp-servers'), []) )
    elif ans['time-config-method'] == 'manual':
        seq.append( Task(configureTimeManually, A(ans, 'mounts', 'ui'), []) )
    # complete upgrade if appropriate:
    if ans['install-type'] == constants.INSTALL_TYPE_REINSTALL:
        seq.append( Task(completeUpgrade, lambda a: [ a['upgrader'] ] + [ a[x] for x in a['upgrader'].completeUpgradeArgs ], []) )

    seq.append(Task(writei18n, A(ans, 'mounts'), []))
    
    # run the users's scripts
    seq.append( Task(scripts.run_scripts, lambda a: ['filesystem-populated',  a['mounts']['root']], []) )

    seq += [
        Task(umountVolumes, A(ans, 'mounts', 'cleanup'), ['cleanup']),
        Task(writeLog, A(ans, 'primary-disk', 'primary-partnum'), [])
        ]

    return seq

def prettyLogAnswers(answers):
    for a in answers:
        if a == 'root-password':
            val = (answers[a][0], '< not printed >')
        else:
            val = answers[a]
        xelogging.log("%s := %s %s" % (a, val, type(val)))

def executeSequence(sequence, seq_name, answers_pristine, ui, cleanup):
    answers = answers_pristine.copy()
    answers['cleanup'] = []
    answers['ui'] = ui

    progress_total = reduce(lambda x, y: x + y,
                            [task.progress_scale for task in sequence])

    pd = None
    if ui:
        pd = ui.progress.initProgressDialog(
            "Installing %s" % MY_PRODUCT_BRAND,
            seq_name, progress_total
            )
    xelogging.log("DISPATCH: NEW PHASE: %s" % seq_name)

    def doCleanup(actions):
        for tag, f, a in actions:
            try:
                apply(f, a)
            except:
                xelogging.log("FAILED to perform cleanup action %s" % tag)

    def progressCallback(x):
        if ui:
            ui.progress.displayProgressDialog(current + x, pd)
        
    try:
        current = 0
        for item in sequence:
            if pd:
                if item.progress_text:
                    text = item.progress_text
                else:
                    text = seq_name

                ui.progress.displayProgressDialog(current, pd, updated_text = text)
            updated_state = item.execute(answers, progressCallback)
            if len(updated_state) > 0:
                xelogging.log(
                    "DISPATCH: Updated state: %s" %
                    str.join("; ", ["%s -> %s" % (v, updated_state[v]) for v in updated_state.keys()])
                    )
                for state_item in updated_state:
                    answers[state_item] = updated_state[state_item]

            current = current + item.progress_scale
    except:
        doCleanup(answers['cleanup'])
        raise
    else:
        if ui and pd:
            ui.progress.clearModelessDialog()

        if cleanup:
            doCleanup(answers['cleanup'])
            del answers['cleanup']

    return answers

def performInstallation(answers, ui_package, interactive):
    xelogging.log("INPUT ANSWERS DICTIONARY:")
    prettyLogAnswers(answers)
    xelogging.log("SCRIPTS DICTIONARY:")
    prettyLogAnswers(scripts.script_dict)

    # update the settings:
    if answers['install-type'] == constants.INSTALL_TYPE_REINSTALL:
        if answers['preserve-settings'] == True:
            xelogging.log("Updating answers dictionary based on existing installation")
            answers.update(answers['installation-to-overwrite'].readSettings())
            xelogging.log("UPDATED ANSWERS DICTIONARY:")
            prettyLogAnswers(answers)
        else:
            # still need to have same keys present in the reinstall (non upgrade)
            # case, but we'll set them to None:
            answers['preserved-license-data'] = None

        # we require guest-disks to always be present, but it is not used other than
        # for status reporting when doing a re-install, so set it to empty rather than
        # trying to guess what the correct value should be.
        answers['guest-disks'] = []
    else:
        if not answers.has_key('sr-type'):
            answers['sr-type'] = constants.SR_TYPE_LVM

    if not answers.has_key('bootloader-location'):
        answers['bootloader-location'] = 'mbr'

    if 'xen-cpuid-masks' not in answers:
        answers['xen-cpuid-masks'] = []

    # Slight hack: we need to write the bridge name to xensource-inventory 
    # further down; compute it here based on the admin interface name if we
    # haven't already recorded it as part of reading settings from an upgrade:
    if not answers.has_key('net-admin-bridge'):
        assert answers['net-admin-interface'].startswith("eth")
        answers['net-admin-bridge'] = "xenbr%s" % answers['net-admin-interface'][3:]

    if 'initial-partitions' not in answers:
        answers['initial-partitions'] = []

    if 'sr-at-end' not in answers:
        answers['sr-at-end'] = True

    if 'preserve-first-partition' not in answers:
        answers['preserve-first-partition'] = False
 
    if 'master' not in answers:
        answers['master'] = None
    answers['branding'] = {}
 
    # perform installation:
    prep_seq = getPrepSequence(answers, interactive)
    new_ans = executeSequence(prep_seq, "Preparing for installation...", answers, ui_package, False)

    # install from main repositories:
    def handleRepos(repos, ans):
        if len(repos) == 0:
            raise RuntimeError, "No repository found at the specified location."
        else:
            seq_name = "Reading package information..."
        repo_seq = getRepoSequence(ans, repos)
        new_ans = executeSequence(repo_seq, seq_name, ans, ui_package, False)
        return new_ans

    new_ans['installed-repos'] = {}
    master_required_list = []
    all_repositories = repository.repositoriesFromDefinition(
        answers['source-media'], answers['source-address']
        )
    if len(new_ans['installed-repos']) == 0 and len(all_repositories) == 0:
        # CA-29016: main repository has vanished
        raise RuntimeError, "No repository found at the specified location."
    if constants.MAIN_REPOSITORY_NAME not in [r.identifier() for r in all_repositories]:
        raise RuntimeError, "Main repository not found at the specified location."

    for driver_repo_def in answers['extra-repos']:
        rtype, rloc, required_list = driver_repo_def
        if rtype == 'local':
            answers['more-media'] = True
        else:
            all_repositories += repository.repositoriesFromDefinition(rtype, rloc)
        master_required_list += filter(lambda r: r not in master_required_list, required_list)

    if answers['preserve-settings'] and 'backup-partnum' in new_ans:
        # mount backup and advertise mountpoint for Supplemental Packs
        chroot_dir = 'tmp/backup'
        backup_device = partitionDevice(new_ans['primary-disk'], new_ans['backup-partnum'])
        backup_fs = util.TempMount(backup_device, 'backup-', options = ['ro'])
        util.assertDir(os.path.join(new_ans['mounts']['root'], chroot_dir))
        util.bindMount(backup_fs.mount_point, os.path.join(new_ans['mounts']['root'], chroot_dir))
        os.environ['XS_PREVIOUS_INSTALLATION'] = '/'+chroot_dir
        
    repeat = True
    while repeat:
        # only install repositories we've not already installed:
        repositories = filter(lambda r: str(r) not in new_ans['installed-repos'],
                              all_repositories)
        if len(repositories) > 0:
            new_ans = handleRepos(repositories, new_ans)

        # get more media?
        repeat = answers.has_key('more-media') and answers['more-media']
        if repeat:
            # find repositories that we installed from removable media:
            for r in repositories:
                if r.accessor().canEject():
                    r.accessor().eject()
            still_need = filter(lambda r: str(r) not in new_ans['installed-repos'], master_required_list)
            accept_media, ask_again, repos = ui_package.installer.more_media_sequence(new_ans['installed-repos'], still_need)
            repeat = accept_media
            answers['more-media'] = ask_again
            all_repositories += repos

    if answers['preserve-settings'] and 'backup-partnum' in new_ans:
        util.umount(os.path.join(new_ans['mounts']['root'], chroot_dir))
        os.rmdir(os.path.join(new_ans['mounts']['root'], chroot_dir))
        backup_fs.unmount()

    # complete the installation:
    fin_seq = getFinalisationSequence(new_ans)
    new_ans = executeSequence(fin_seq, "Completing installation...", new_ans, ui_package, True)

    if answers['source-media'] == 'local':
        for r in repositories:
            if r.accessor().canEject():
                r.accessor().eject()

    return new_ans

def checkRepoDeps(repo, installed_repos, branding):
    xelogging.log("Checking for dependencies of %s" % repo.identifier())
    missing_repos = repo.check_requires(installed_repos)
    if len(missing_repos) > 0:
        text = "Repository dependency error:\n\n"
        text += '\n'.join(missing_repos)
        raise RuntimeError, text

    # preserve branding
    if repo.identifier() == MAIN_REPOSITORY_NAME:
        branding.update({ 'platform-name': repo._product_brand,
                          'platform-version': repo._product_version.ver_as_string() })
    elif repo.identifier() == MAIN_XS_REPOSITORY_NAME:
        branding.update({ 'product-brand': repo._product_brand,
                          'product-version': repo._product_version.ver_as_string(),
                          'product-build': repo._product_version.build_as_string() })
    return branding

def installPackage(progress_callback, mounts, package):
    package.install(mounts['root'], progress_callback)

# Time configuration:
def configureNTP(mounts, ntp_servers):
    # If NTP servers were specified, update the NTP config file:
    if len(ntp_servers) > 0:
        ntpsconf = open("%s/etc/ntp.conf" % mounts['root'], 'r')
        lines = ntpsconf.readlines()
        ntpsconf.close()

        lines = filter(lambda x: not x.startswith('server '), lines)

        ntpsconf = open("%s/etc/ntp.conf" % mounts['root'], 'w')
        for line in lines:
            ntpsconf.write(line)
        for server in ntp_servers:
            ntpsconf.write("server %s\n" % server)
        ntpsconf.close()

    # now turn on the ntp service:
    util.runCmd2(['chroot', mounts['root'], 'chkconfig', 'ntpd', 'on'])

def configureTimeManually(mounts, ui_package):
    # display the Set Time dialog in the chosen UI:
    rc, time = util.runCmd2(['chroot', mounts['root'], 'timeutil', 'getLocalTime'], with_stdout = True)
    assert rc == 0
    answers = {}
    ui_package.installer.screens.set_time(answers, util.parseTime(time))
        
    newtime = answers['localtime']
    timestr = "%04d-%02d-%02d %02d:%02d:00" % \
              (newtime.year, newtime.month, newtime.day,
               newtime.hour, newtime.minute)
        
    # chroot into the dom0 and set the time:
    assert util.runCmd2(['chroot', mounts['root'], 'timeutil', 'setLocalTime', '%s' % timestr]) == 0
    assert util.runCmd2(['hwclock', '--utc', '--systohc']) == 0


def inspectTargetDisk(disk, existing, initial_partitions, zap_utility_partitions ,preserve_first_partition):
    
    if existing:
        # upgrade, use existing partitioning scheme
        tool = PartitionTool(existing.primary_disk)
        
        primary_part = tool.partitionNumber(existing.root_device)
        return (primary_part, primary_part+1, primary_part+2)
    
    tool = PartitionTool(disk)

    # If answerfile says to fake a utility partition then do it here
    if len(initial_partitions) > 0:
        for part in initial_partitions:
            tool.deletePartition(part['number'])
            tool.createPartition(part['id'], part['size'], part['number'])
        tool.commit(log = True)

    # Preserve any utility partitions unless user told us to zap 'em
    primary_part = 1
    if preserve_first_partition:
        primary_part += 1
    elif not zap_utility_partitions:
        utilparts = tool.utilityPartitions()
        primary_part += max(utilparts+[0])
        if primary_part > 2:
            raise RuntimeError, "Installer only supports a single Utility Partition at partition 1, but found Utility Partitions at %s" % str(utilparts)

    # Return numbers of primary, backup, and SR partitions
    return (primary_part, primary_part+1, primary_part+2)

# Determine which partition table type to use
def selectPartitionTableType(disk, install_type, primary_part):
    if not constants.GPT_SUPPORT:
        return 'DOS'

    tool = PartitionTool(disk)

    # If not a fresh install then use same partition table as before
    if install_type != INSTALL_TYPE_FRESH:
        return tool.partTableType

    # If we are preserving partition 1 then we need to preserve the 
    # partition table type as we are probably chain booting from that.
    if primary_part > 1:
        return tool.partTableType

    # This is a fresh install and we do not need to preserve partition1
    # Use GPT because it is better.
    return 'GPT'

def removeBlockingVGs(disks):
    for vg in diskutil.findProblematicVGs(disks):
        util.runCmd2(['vgreduce', '--removemissing', vg])
        util.runCmd2(['lvremove', vg])
        util.runCmd2(['vgremove', vg])

###
# Functions to write partition tables to disk

def writeDom0DiskPartitions(disk, primary_partnum, backup_partnum, storage_partnum, sr_at_end, partition_table_type):
    # we really don't want to screw this up...
    assert type(disk) == str
    assert disk[:5] == '/dev/'

    if not os.path.exists(disk):
        raise RuntimeError, "The disk %s could not be found." % disk

    # check disk is large enough
    if diskutil.blockSizeToGBSize(diskutil.getDiskDeviceSize(disk)) < constants.min_primary_disk_size:
        raise RuntimeError, "The disk %s is smaller than %dGB." % (disk, constants.min_primary_disk_size)

    tool = PartitionTool(disk, partition_table_type)
    for num, part in tool.iteritems():
        if num >= primary_partnum:
            tool.deletePartition(num)
        else:
            tool.setActiveFlag(False, num)
    tool.createPartition(tool.ID_LINUX, sizeBytes = root_size * 2**20, number = primary_partnum, active = True)
    if backup_partnum > 0:
        tool.createPartition(tool.ID_LINUX, sizeBytes = root_size * 2**20, number = backup_partnum)
    if storage_partnum > 0:
        tool.createPartition(tool.ID_LINUX_LVM, number = storage_partnum)

    if not sr_at_end:
        # For upgrade testing, out-of-order partition layout
        new_parts = {}

        new_parts[primary_partnum] = {'start': tool.partitions[primary_partnum]['start'] + tool.partitions[storage_partnum]['size'],
                                      'size': tool.partitions[primary_partnum]['size'],
                                      'id': tool.partitions[primary_partnum]['id'],
                                      'active': tool.partitions[primary_partnum]['active']}
        if backup_partnum > 0:
            new_parts[backup_partnum] = {'start': new_parts[primary_partnum]['start'] + new_parts[primary_partnum]['size'],
                                         'size': tool.partitions[backup_partnum]['size'],
                                         'id': tool.partitions[backup_partnum]['id'],
                                         'active': tool.partitions[backup_partnum]['active']}
        new_parts[storage_partnum] = {'start': tool.partitions[primary_partnum]['start'],
                                      'size': tool.partitions[storage_partnum]['size'],
                                      'id': tool.partitions[storage_partnum]['id'],
                                      'active': tool.partitions[storage_partnum]['active']}

        for part in (primary_partnum, backup_partnum, storage_partnum):
            if part > 0:
                tool.deletePartition(part)
                tool.createPartition(new_parts[part]['id'], new_parts[part]['size'] * tool.sectorSize, part,
                                     new_parts[part]['start'] * tool.sectorSize, new_parts[part]['active'])

    tool.commit(log = True)

def writeGuestDiskPartitions(primary_disk, guest_disks, partition_table_type):
    # At the moment this code uses the same partition table type for Guest Disks as it 
    # does for the root disk.  But we could choose to always use 'GPT' for guest disks.
    # TODO: Decide!
    for gd in guest_disks:
        if gd != primary_disk:
            # we really don't want to screw this up...
            assert type(gd) == str
            assert gd[:5] == '/dev/'

            tool = PartitionTool(gd, partition_table_type)
            tool.deletePartitions(tool.partitions.keys())
            tool.commit(log = True)

def getSRPhysDevs(primary_disk, storage_partnum, guest_disks):
    def sr_partition(disk):
        if disk == primary_disk:
            return partitionDevice(disk, storage_partnum)
        else:
            return disk

    return [sr_partition(disk) for disk in guest_disks]

def prepareStorageRepositories(mounts, primary_disk, storage_partnum, guest_disks, sr_type):
    
    if len(guest_disks) == 0:
        xelogging.log("No storage repository requested.")
        return None

    xelogging.log("Arranging for storage repositories to be created at first boot...")

    partitions = getSRPhysDevs(primary_disk, storage_partnum, guest_disks)

    sr_type_strings = { constants.SR_TYPE_EXT: 'ext', 
                        constants.SR_TYPE_LVM: 'lvm' }
    sr_type_string = sr_type_strings[sr_type]

    # write a config file for the prepare-storage firstboot script:
    
    links = map(lambda x: diskutil.idFromPartition(x) or x, partitions)
    fd = open(os.path.join(mounts['root'], constants.FIRSTBOOT_DATA_DIR, 'default-storage.conf'), 'w')
    print >>fd, "XSPARTITIONS='%s'" % str.join(" ", links)
    print >>fd, "XSTYPE='%s'" % sr_type_string
    # Legacy names
    print >>fd, "PARTITIONS='%s'" % str.join(" ", links)
    print >>fd, "TYPE='%s'" % sr_type_string
    fd.close()
    
###
# Create dom0 disk file-systems:

def createDom0DiskFilesystems(disk, primary_partnum):
    rc, err = util.runCmd2(["mkfs.%s" % rootfs_type, "-L", rootfs_label, partitionDevice(disk, primary_partnum)], with_stderr = True)
    if rc != 0:
        raise RuntimeError, "Failed to create filesystem: %s" % err

def __mkinitrd(mounts, partition, kernel_version):

    cmd = ['mkinitrd', '-v']
    args = ['--theme=/usr/share/splash']
    if isDeviceMapperNode(partition):
        # [multipath-root]: /etc/fstab specifies the rootdev by LABEL so we need this to make sure mkinitrd
        # picks up the master device and not the slave 
        args.append('--rootdev='+ partition)
    else:
        args.append('--without-multipath')

    try:
        util.bindMount('/sys', os.path.join(mounts['root'], 'sys'))
        util.bindMount('/dev', os.path.join(mounts['root'], 'dev'))
        util.bindMount('/proc', os.path.join(mounts['root'], 'proc'))
        util.mount('none', os.path.join(mounts['root'], 'tmp'), None, 'tmpfs')

        # Run mkinitrd inside dom0 chroot
        output_file = os.path.join("/boot", "initrd-%s.img" % kernel_version)

        cmd = ['mkinitrd', '--latch']
        cmd.extend( args )
        if util.runCmd2(['chroot', mounts['root']] + cmd) != 0:
            raise RuntimeError, "Failed to latch arguments for initrd."
        
        cmd = ['mkinitrd', '-v']
        cmd.extend( args )
        cmd.extend([output_file, kernel_version])
        if util.runCmd2(['chroot', mounts['root']] + cmd) != 0:
            raise RuntimeError, "Failed to create initrd for %s.  This is often due to using an installer that is not the same version of %s as your installation source." % (kernel_version, MY_PRODUCT_BRAND)
        # Save command used to create initrd in <initrd_filename>.cmd
        cmd_logfile = os.path.join(mounts['root'], output_file[1:] + '.cmd')
        open(cmd_logfile, "w").write(' '.join(cmd) + '\n')
    finally:
        util.umount(os.path.join(mounts['root'], 'sys'))
        util.umount(os.path.join(mounts['root'], 'dev'))
        util.umount(os.path.join(mounts['root'], 'proc'))
        util.umount(os.path.join(mounts['root'], 'tmp'))

class KernelNotFound(Exception):
    pass
def getKernelVersion(rootfs_mount, kextra):
    """ Returns a list of installed kernel version of type kextra, e.g. 'xen'. """
    chroot = ['chroot', rootfs_mount, 'rpm', '-q', 'kernel-%s' % kextra, '--qf', '%%{VERSION}-%%{RELEASE}%s\n' % kextra]
    rc, out = util.runCmd2(chroot, with_stdout = True)
    if rc != 0:
        raise KernelNotFound, "Required package kernel-%s not found." % kextra

    out = out.strip().split("\n")
    assert len(out) >= 1, "Required package kernel-%s not found." % kextra
    return out[-1]

def configureSRMultipathing(mounts, primary_disk):
    # Only called on fresh installs:
    # Configure multipathed SRs iff root disk is multipathed
    fd = open(os.path.join(mounts['root'], constants.FIRSTBOOT_DATA_DIR, 'sr-multipathing.conf'),'w')
    if isDeviceMapperNode(primary_disk):
        fd.write("MULTIPATHING_ENABLED='True'\n")
    else:
        fd.write("MULTIPATHING_ENABLED='False'\n")
    fd.close()

def mkinitrd(mounts, primary_disk, primary_partnum):
    xen_kernel_version = getKernelVersion(mounts['root'], 'xen')
    kdump_kernel_version = getKernelVersion(mounts['root'], 'kdump')
    partition = partitionDevice(primary_disk, primary_partnum)

    if diskutil.is_iscsi(primary_disk):

        # Mkinitrd needs node files so it can extract 
        # details about the iscsi root disk
        src = '/etc/iscsi/nodes'
        dst = os.path.join(mounts['root'], 'etc/iscsi/')
        util.runCmd2(['cp','-a', src, dst])

        if isDeviceMapperNode(primary_disk):

            # Multipath failover between iSCSI disks requires iscsid
            # to be running as it handles the error path
            cmd = ['chroot', mounts['root'], 
                   'chkconfig', '--level', '2345', 'open-iscsi', 'on']
            if util.runCmd2(cmd):
                raise RuntimeError, "Failed to chkconfig open-iscsi on"
            # Open-iscsi needs an initiator name to start
            src='/etc/iscsi/initiatorname.iscsi'
            dst=os.path.join(mounts['root'],'etc/iscsi/initiatorname.iscsi')
            if not os.path.exists(dst):
                cmd = ['cp','-a', src, dst]
                if util.runCmd2(cmd):
                    raise RuntimeError, "Failed to copy initiatorname.iscsi"

    __mkinitrd(mounts, partition, xen_kernel_version)
    __mkinitrd(mounts, partition, kdump_kernel_version)
 
    # make the initrd-2.6-xen.img symlink:
    os.symlink("initrd-%s.img" % xen_kernel_version, "%s/boot/initrd-2.6-xen.img" % mounts['root'])

def configureKdump(mounts):
    # set kdump config to handle known errata
    rc, out = util.runCmd2(['lspci', '-n'], with_stdout = True)
    if rc == 0 and ('10de:0360' in out or '10de:0364' in out):
        kdcfile = open("%s/etc/sysconfig/kdump" % mounts['root'], 'a')
        kdcfile.write('KDUMP_KERNEL_CMDLINE_EXTRA="irqpoll maxcpus=1 reset_devices no-hlt"\n')
        kdcfile.close()

def buildBootLoaderMenu(xen_kernel_version, boot_config, serial, xen_cpuid_masks):
    common_xen_params = "mem=%dG dom0_max_vcpus=%d dom0_mem=%dM" % (constants.XEN_MEM, constants.DOM0_VCPUS, constants.DOM0_MEM)
    safe_xen_params = "nosmp noreboot noirqbalance acpi=off noapic"
    xen_mem_params = "lowmem_emergency_pool=1M crashkernel=64M@32M"
    mask_params = ' '.join(xen_cpuid_masks)
    if len(mask_params):
        mask_params = ' '+mask_params
    common_kernel_params = "root=LABEL=%s ro" % constants.rootfs_label
    kernel_console_params = "xencons=hvc console=hvc0"

    e = bootloader.MenuEntry("/boot/xen.gz",
                             common_xen_params+" "+xen_mem_params+mask_params+" console= vga=mode-0x0311",
                             "/boot/vmlinuz-2.6-xen",
                             common_kernel_params+" "+kernel_console_params+" console=tty0 quiet vga=785 splash",
                             "/boot/initrd-2.6-xen.img", MY_PRODUCT_BRAND)
    boot_config.append("xe", e)
    if serial:
        xen_serial_params = "%s console=%s,vga" % (serial.xenFmt(), serial.port)
        
        e = bootloader.MenuEntry("/boot/xen.gz",
                                 ' '.join([xen_serial_params, common_xen_params, xen_mem_params+mask_params]),
                                 "/boot/vmlinuz-2.6-xen",
                                 common_kernel_params+" console=tty0 "+kernel_console_params,
                                 "/boot/initrd-2.6-xen.img", MY_PRODUCT_BRAND+" (Serial)")
        boot_config.append("xe-serial", e)
        e = bootloader.MenuEntry("/boot/xen.gz",
                                 ' '.join([safe_xen_params, common_xen_params, xen_serial_params]),
                                 "/boot/vmlinuz-2.6-xen",
                                 ' '.join(["nousb", common_kernel_params, "console=tty0", kernel_console_params]),
                                 "/boot/initrd-2.6-xen.img", MY_PRODUCT_BRAND+" in Safe Mode")
        boot_config.append("safe", e)
    e = bootloader.MenuEntry("/boot/xen-%s.gz" % version.XEN_VERSION,
                             common_xen_params+" "+xen_mem_params+mask_params,
                             "/boot/vmlinuz-%s" % xen_kernel_version,
                             ' '.join([common_kernel_params, kernel_console_params, "console=tty0"]),
                             "/boot/initrd-%s.img" % xen_kernel_version, 
                             "%s (Xen %s / Linux %s)" % (MY_PRODUCT_BRAND, version.XEN_VERSION, xen_kernel_version))
    boot_config.append("fallback", e)
    if serial:
        e = bootloader.MenuEntry("/boot/xen-%s.gz" % version.XEN_VERSION,
                                 ' '.join([xen_serial_params, common_xen_params, xen_mem_params+mask_params]),
                                 "/boot/vmlinuz-%s" % xen_kernel_version,
                                 common_kernel_params+" console=tty0 "+kernel_console_params,
                                 "/boot/initrd-%s.img" % xen_kernel_version, 
                                 "%s (Serial, Xen %s / Linux %s)" % (MY_PRODUCT_BRAND, version.XEN_VERSION, xen_kernel_version))
        boot_config.append("fallback-serial", e)

def installBootLoader(mounts, disk, partition_table_type, primary_partnum, serial, boot_serial, cpuid_masks, location = 'mbr'):
    
    assert(location == 'mbr' or location == 'partition')
    
    # prepare extra mounts for installing bootloader:
    util.bindMount("/dev", "%s/dev" % mounts['root'])
    util.bindMount("/sys", "%s/sys" % mounts['root'])

    # This is a nasty hack but unavoidable (I think):
    #
    # The bootloader tries to work out what the root device is but
    # this is confused within the chroot.  Therefore, we fake out
    # /proc/mounts with the correct data. If /etc/mtab is not a
    # symlink (to /proc/mounts) then we fake that out too.
    f = open("%s/proc/mounts" % mounts['root'], 'w')
    f.write("%s / %s rw 0 0\n" % (partitionDevice(disk, primary_partnum), constants.rootfs_type))
    f.close()
    if not os.path.islink("%s/etc/mtab" % mounts['root']):
        f = open("%s/etc/mtab" % mounts['root'], 'w')
        f.write("%s / %s rw 0 0\n" % (partitionDevice(disk, primary_partnum), constants.rootfs_type))
        f.close()

    try:
        fn = os.path.join(mounts['boot'], "extlinux.conf")
        boot_config = bootloader.Bootloader('extlinux', fn, default = boot_serial and 'xe-serial' or 'xe', timeout = 50,
                                            serial = serial and {'port': serial.id, 'baud': int(serial.baud)} or None,
                                            location = location)
        buildBootLoaderMenu(getKernelVersion(mounts['root'], 'xen'), boot_config, serial, cpuid_masks)
        util.assertDir(os.path.dirname(fn))
        boot_config.commit()

        installExtLinux(mounts, disk, partition_table_type, location)

        if serial:
            # ensure a getty will run on the serial console
            old = open("%s/etc/inittab" % mounts['root'], 'r')
            new = open('/tmp/inittab', 'w')

            for line in old:
                if line.startswith("s%d:" % serial.id):
                    new.write(re.sub(r'getty \S+ \S+', "getty %s %s" % (serial.dev, serial.baud), line))
                else:
                    new.write(line)

            old.close()
            new.close()
            shutil.move('/tmp/inittab', "%s/etc/inittab" % mounts['root'])
    finally:
        # unlink /proc/mounts
        if os.path.exists("%s/proc/mounts" % mounts['root']):
            os.unlink("%s/proc/mounts" % mounts['root'])
        # done installing - undo our extra mounts:
        util.umount("%s/sys" % mounts['root'])
        util.umount("%s/dev" % mounts['root'])

def installExtLinux(mounts, disk, partition_table_type, location = 'mbr'):

    # As of v4.02 syslinux installs comboot modules under /boot/extlinux/.
    # However we continue to copy the ones we need to /boot so we can write the config file there.
    # We need to do this because old installers are needed to restore old XS images from the backup
    # partition, and these need to read the config on the current partition.  Oops.
    # This also means we avoid find and fix all the other scripts which assume extlinux.conf is under /boot.

    rc, err = util.runCmd2(["chroot", mounts['root'], "/sbin/extlinux", "--install", "/boot"], with_stderr = True)
    if rc != 0:
        raise RuntimeError, "Failed to install bootloader: %s" % err

    for m in ["mboot", "menu", "chain"]:
        if not os.path.exists("%s/%s.c32" % (mounts['boot'], m)):
            os.link("%s/extlinux/%s.c32" % (mounts['boot'], m), "%s/%s.c32" % (mounts['boot'], m))

    # must be able to restore pre-6.0 systems
    base_dir = mounts['root'] + "/usr/share/syslinux"
    if not os.path.exists(base_dir):
        base_dir = mounts['root']+"/usr/lib/syslinux"
    if location == 'mbr':
        if partition_table_type == 'DOS':
            mbr = base_dir + "/mbr.bin"
        elif partition_table_type == 'GPT':
            mbr = base_dir + "/gptmbr.bin"
        else:
            raise Exception("Only DOS and GPT partition tables supported")

        # Write image to MBR
        xelogging.log("Installing %s to %s" % (mbr, disk))
        assert os.path.exists(mbr)
        assert util.runCmd2(["dd", "if=%s" % mbr, "of=%s" % disk]) == 0

##########
# mounting and unmounting of various volumes

def mountVolumes(primary_disk, primary_partnum, cleanup):
    mounts = {'root': '/tmp/root',
              'boot': '/tmp/root/boot'}

    rootp = partitionDevice(primary_disk, primary_partnum)
    util.assertDir('/tmp/root')
    util.mount(rootp, mounts['root'])
    new_cleanup = cleanup + [ ("umount-/tmp/root", util.umount, (mounts['root'], )) ]
    return mounts, new_cleanup
 
def umountVolumes(mounts, cleanup, force = False):
    util.umount(mounts['root'])
    cleanup = filter(lambda (tag, _, __): tag != "umount-%s" % mounts['root'],
                     cleanup)
    return cleanup

##########
# second stage install helpers:
    
def doDepmod(mounts):
    util.runCmd2(['chroot', mounts['root'], 'depmod', getKernelVersion(mounts['root'], 'xen')]) == 0

def writeKeyboardConfiguration(mounts, keymap):
    util.assertDir("%s/etc/sysconfig/" % mounts['root'])
    if not keymap:
        keymap = 'us'
        xelogging.log("No keymap specified, defaulting to 'us'")

    kbdfile = open("%s/etc/sysconfig/keyboard" % mounts['root'], 'w')
    kbdfile.write("KEYBOARDTYPE=pc\n")
    kbdfile.write("KEYTABLE=%s\n" % keymap)
    kbdfile.close()

def prepareSwapfile(mounts):
    util.assertDir("%s/var/swap" % mounts['root'])
    util.runCmd2(['dd', 'if=/dev/zero',
                  'of=%s' % os.path.join(mounts['root'], constants.swap_location.lstrip('/')),
                  'bs=1024', 'count=%d' % (constants.swap_size * 1024)])
    util.bindMount("/proc", "%s/proc" % mounts['root'])
    util.bindMount("/sys", "%s/sys" % mounts['root'])
    util.runCmd2(['chroot', mounts['root'], 'mkswap', constants.swap_location])
    util.umount("%s/proc" % mounts['root'])
    util.umount("%s/sys" % mounts['root'])

def writeFstab(mounts):
    fstab = open(os.path.join(mounts['root'], 'etc/fstab'), "w")
    fstab.write("LABEL=%s    /         %s     defaults   1  1\n" % (rootfs_label, rootfs_type))
    if os.path.exists(os.path.join(mounts['root'], constants.swap_location.lstrip('/'))):
        fstab.write("%s          swap      swap   defaults   0  0\n" % (constants.swap_location))
    fstab.write("none        /dev/pts  devpts defaults   0  0\n")
    fstab.write("none        /dev/shm  tmpfs  defaults   0  0\n")
    fstab.write("none        /proc     proc   defaults   0  0\n")
    fstab.write("none        /sys      sysfs  defaults   0  0\n")
    fstab.write("/opt/xensource/packages/iso/XenCenter.iso   /var/xen/xc-install   iso9660   loop,ro   0  0\n")
    fstab.close()

def enableAgent(mounts, network_backend):
    util.runCmd2(['chroot', mounts['root'], 'chkconfig', '--del', 'xend'])

    if network_backend == constants.NETWORK_BACKEND_VSWITCH:
        vswitch = ['openvswitch']
    else:
        vswitch = []
        
    for service in ['snapwatchd'] + vswitch:
        util.runCmd2(['chroot', mounts['root'], 'chkconfig', '--add', service])
    util.assertDir(os.path.join(mounts['root'], constants.BLOB_DIRECTORY))

def writeResolvConf(mounts, hn_conf, ns_conf):
    (manual_hostname, hostname) = hn_conf
    (manual_nameservers, nameservers) = ns_conf

    if manual_nameservers:
        resolvconf = open("%s/etc/resolv.conf" % mounts['root'], 'w')
        if manual_hostname:
            # /etc/hostname:
            eh = open('%s/etc/hostname' % mounts['root'], 'w')
            eh.write(hostname + "\n")
            eh.close()

            # 'search' option in resolv.conf
            try:
                dot = hostname.index('.')
                if dot + 1 != len(hostname):
                    dname = hostname[dot + 1:]
                    resolvconf.write("search %s\n" % dname)
            except:
                pass
        for ns in nameservers:
            if ns != "":
                resolvconf.write("nameserver %s\n" % ns)
        resolvconf.close()


def setTimeZone(mounts, tz):
    # write the time configuration to the /etc/sysconfig/clock
    # file in dom0:
    timeconfig = open("%s/etc/sysconfig/clock" % mounts['root'], 'w')
    timeconfig.write("ZONE=%s\n" % tz)
    timeconfig.write("UTC=true\n")
    timeconfig.write("ARC=false\n")
    timeconfig.close()

    # make the localtime link:
    assert util.runCmd2(['ln', '-sf', '/usr/share/zoneinfo/%s' % tz, 
                         '%s/etc/localtime' % mounts['root']]) == 0

def setRootPassword(mounts, root_pwd):
    # avoid using shell here to get around potential security issues.  Also
    # note that chpasswd needs -m to allow longer passwords to work correctly
    # but due to a bug in the RHEL5 version of this tool it segfaults when this
    # option is specified, so we have to use passwd instead if we need to 
    # encrypt the password.  Ugh.
    (pwdtype, root_password) = root_pwd
    if pwdtype == 'pwdhash':
        cmd = ["/usr/sbin/chroot", mounts["root"], "chpasswd", "-e"]
        pipe = subprocess.Popen(cmd, stdin = subprocess.PIPE,
                                     stdout = subprocess.PIPE)
        pipe.communicate('root:%s\n' % root_password)
        assert pipe.wait() == 0
    else: 
        cmd = ["/usr/sbin/chroot", mounts['root'], "passwd", "--stdin", "root"]
        pipe = subprocess.Popen(cmd, stdin = subprocess.PIPE,
                                     stdout = subprocess.PIPE,
                                     stderr = subprocess.PIPE)
        pipe.communicate(root_password + "\n")
        assert pipe.wait() == 0

# write /etc/sysconfig/network-scripts/* files
def configureNetworking(mounts, admin_iface, admin_bridge, admin_config, hn_conf, ns_conf, nethw, preserve_settings, network_backend):
    """ Writes configuration files that the firstboot scripts will consume to
    configure interfaces via the CLI.  Writes a loopback device configuration.
    to /etc/sysconfig/network-scripts, and removes any other configuration
    files from that directory."""

    (manual_hostname, hostname) = hn_conf
    (manual_nameservers, nameservers) = ns_conf
    domain = None
    if manual_hostname:
        dot = hostname.find('.')
        if dot != -1:
            domain = hostname[dot+1:]

    # always set network backend
    util.assertDir(os.path.join(mounts['root'], 'etc/xensource'))
    nwconf = open("%s/etc/xensource/network.conf" % mounts["root"], "w")
    nwconf.write("%s\n" % network_backend)
    xelogging.log("Writing %s to /etc/xensource/network.conf" % network_backend)
    nwconf.close()

    mgmt_conf_file = os.path.join(mounts['root'], constants.FIRSTBOOT_DATA_DIR, 'management.conf')
    if not os.path.exists(mgmt_conf_file):
        mc = open(mgmt_conf_file, 'w')
        print >>mc, "LABEL='%s'" % admin_iface
        print >>mc, "MODE='%s'" % ((admin_config.mode == netinterface.NetInterface.Static) and 'static' or 'dhcp')
        if admin_config.mode == netinterface.NetInterface.Static:
            print >>mc, "IP='%s'" % admin_config.ipaddr
            print >>mc, "NETMASK='%s'" % admin_config.netmask
            if admin_config.gateway:
                print >>mc, "GATEWAY='%s'" % admin_config.gateway
            if manual_nameservers:
                for i in range(len(nameservers)):
                    print >>mc, "DNS%d='%s'" % (i+1, nameservers[i])
            if domain:
                print >>mc, "DOMAIN='%s'" % domain
        mc.close()

    if preserve_settings:
        return

    # Clean install only below this point

    util.assertDir(os.path.join(mounts['root'], constants.FIRSTBOOT_DATA_DIR))

    network_scripts_dir = os.path.join(mounts['root'], 'etc/sysconfig/network-scripts')

    # remove any files that may be present in the filesystem already, 
    # particularly those created by kudzu:
    network_scripts = os.listdir(network_scripts_dir)
    for s in filter(lambda x: x.startswith('ifcfg-'), network_scripts):
        os.unlink(os.path.join(network_scripts_dir, s))

    # write the configuration file for the loopback interface
    lo = open(os.path.join(network_scripts_dir, 'ifcfg-lo'), 'w')
    lo.write("DEVICE=lo\n")
    lo.write("IPADDR=127.0.0.1\n")
    lo.write("NETMASK=255.0.0.0\n")
    lo.write("NETWORK=127.0.0.0\n")
    lo.write("BROADCAST=127.255.255.255\n")
    lo.write("ONBOOT=yes\n")
    lo.write("NAME=loopback\n")
    lo.close()

    save_dir = os.path.join(mounts['root'], constants.FIRSTBOOT_DATA_DIR, 'initial-ifcfg')
    util.assertDir(save_dir)

    # Write out initial network configuration file for management interface:
    dbcache_file = os.path.join(mounts['root'], constants.DBCACHE)
    util.assertDir(os.path.dirname(dbcache_file))
    dbcache_fd = open(dbcache_file, 'w')
    pif_uid = util.getUUID()
    network_uid = util.getUUID()

    dbcache_fd.write('<?xml version="1.0" ?>\n<xenserver-network-configuration>\n')
    admin_config.writePif(admin_iface, dbcache_fd, pif_uid, network_uid)
    dbcache_fd.write('\t<network ref="OpaqueRef:%s">\n' % network_uid)
    dbcache_fd.write('\t\t<uuid>InitialManagementNetwork</uuid>\n')
    dbcache_fd.write('\t\t<PIFs>\n\t\t\t<PIF>OpaqueRef:%s</PIF>\n\t\t</PIFs>\n' % pif_uid)
    dbcache_fd.write('\t\t<bridge>%s</bridge>\n' % admin_bridge)
    dbcache_fd.write('\t\t<other_config/>\n\t</network>\n')
    dbcache_fd.write('</xenserver-network-configuration>\n')

    dbcache_fd.close()
    util.runCmd2(['cp', '-p', dbcache_file, save_dir])

    # now we need to write /etc/sysconfig/network
    nfd = open("%s/etc/sysconfig/network" % mounts["root"], "w")
    nfd.write("NETWORKING=yes\n")
    if manual_hostname:
        nfd.write("HOSTNAME=%s\n" % hostname)
    else:
        nfd.write("HOSTNAME=localhost.localdomain\n")
    nfd.close()

    if network_backend == constants.NETWORK_BACKEND_VSWITCH:
        # CA-51684: blacklist bridge module
        bfd = open("%s/etc/modprobe.d/blacklist-bridge" % mounts["root"], "w")
        bfd.write("install bridge /bin/true\n")
        bfd.close()

    # EA-1069 - write static-rules.conf and dynamic-rules.conf
    if not os.path.exists(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/.from_install/')):
        os.makedirs(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/.from_install/'), 0775)

    static_text = (
        "# Static rules.  Autogenerated by the installer from either the answerfile or from previous install\n"
        "# WARNING - rules in this file override the 'lastboot' assignment of names,\n"
        "#           so editing it may cause unexpected renaming on next boot\n\n"
        "# Rules are of the form:\n"
        "#   target name: id method = \"value\"\n\n"
        
        "# target name must be in the form eth*\n"
        "# id methods are:\n"
        "#   mac: value should be the mac address of a device (e.g. DE:AD:C0:DE:00:00)\n"
        "#   pci: value should be the pci bus location of the device (e.g. 0000:01:01.1)\n"
        "#   ppn: value should be the result of the biosdevname physical naming policy of a device (e.g. pci1p1)\n"
        "#   label: value should be the SMBios label of a device (for SMBios 2.6 or above)\n\n")
    static_text += '\n'.join(netutil.srules)
    
    fout1 = open(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/static-rules.conf'), "w")
    fout1.write(static_text)
    fout1.close()
    fout2 = open(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/.from_install/static-rules.conf'), "w")
    fout2.write(static_text)
    fout2.close()

    dynamic_text = ("# Automatically adjusted file.  Do not edit unless you are certain you know how to\n")
    drules_text = ("%s" % netutil.drules).replace("'",'"')
    dynamic_text += '{"lastboot":%s,"old":[]}' % drules_text

    fout3 = open(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/dynamic-rules.json'), "w")
    fout3.write(dynamic_text)
    fout3.close()
    fout4 = open(os.path.join(mounts['root'], 'etc/sysconfig/network-scripts/interface-rename-data/.from_install/dynamic-rules.json'), "w")
    fout4.write(dynamic_text)
    fout4.close()


# use kudzu to write initial modprobe-conf:
def writeModprobeConf(mounts):
    # CA-21996: kudzu can get confused and write ifcfg files for the
    # the wrong interface. If we move the network-scripts sideways
    # then it still performs its other tasks.
    os.rename("%s/etc/sysconfig/network-scripts" % mounts['root'], 
              "%s/etc/sysconfig/network-scripts.hold" % mounts['root'])

    util.bindMount("/proc", "%s/proc" % mounts['root'])
    util.bindMount("/sys", "%s/sys" % mounts['root'])
    util.runCmd2(['chroot', mounts['root'], 'kudzu', '-q', '-k', getKernelVersion(mounts['root'], 'xen')]) == 0
    util.umount("%s/proc" % mounts['root'])
    util.umount("%s/sys" % mounts['root'])

    # restore directory
    os.rename("%s/etc/sysconfig/network-scripts.hold" % mounts['root'], 
              "%s/etc/sysconfig/network-scripts" % mounts['root'])

def writeInventory(installID, controlID, mounts, primary_disk, backup_partnum, storage_partnum, guest_disks, admin_bridge, branding):
    inv = open(os.path.join(mounts['root'], constants.INVENTORY_FILE), "w")
    default_sr_physdevs = getSRPhysDevs(primary_disk, storage_partnum, guest_disks)
    if 'product-brand' in branding:
       inv.write("PRODUCT_BRAND='%s'\n" % branding['product-brand'])
    if PRODUCT_NAME:
       inv.write("PRODUCT_NAME='%s'\n" % PRODUCT_NAME)
    if 'product-version' in branding:
       inv.write("PRODUCT_VERSION='%s'\n" % branding['product-version'])
    if COMPANY_NAME:
       inv.write("COMPANY_NAME='%s'\n" % COMPANY_NAME)
    if COMPANY_NAME_SHORT:
       inv.write("COMPANY_NAME_SHORT='%s'\n" % COMPANY_NAME_SHORT)
    if BRAND_CONSOLE:
       inv.write("BRAND_CONSOLE='%s'\n" % BRAND_CONSOLE) 
    inv.write("PLATFORM_NAME='%s'\n" % branding['platform-name'])
    inv.write("PLATFORM_VERSION='%s'\n" % branding['platform-version'])

    inv.write("BUILD_NUMBER='%s'\n" % branding.get('product-build', BUILD_NUMBER))
    inv.write("KERNEL_VERSION='%s'\n" % version.KERNEL_VERSION)
    inv.write("XEN_VERSION='%s'\n" % version.XEN_VERSION)
    inv.write("INSTALLATION_DATE='%s'\n" % str(datetime.datetime.now()))
    inv.write("PRIMARY_DISK='%s'\n" % (diskutil.idFromPartition(primary_disk) or primary_disk))
    if backup_partnum > 0:
        inv.write("BACKUP_PARTITION='%s'\n" % (diskutil.idFromPartition(partitionDevice(primary_disk, backup_partnum)) or partitionDevice(primary_disk, backup_partnum)))
    inv.write("INSTALLATION_UUID='%s'\n" % installID)
    inv.write("CONTROL_DOMAIN_UUID='%s'\n" % controlID)
    inv.write("DEFAULT_SR_PHYSDEVS='%s'\n" % " ".join(default_sr_physdevs))
    inv.write("DOM0_MEM='%d'\n" % constants.DOM0_MEM)
    inv.write("MANAGEMENT_INTERFACE='%s'\n" % admin_bridge)
    inv.close()

def touchSshAuthorizedKeys(mounts):
    util.assertDir("%s/root/.ssh/" % mounts['root'])
    fh = open("%s/root/.ssh/authorized_keys" % mounts['root'], 'a')
    fh.close()


################################################################################
# OTHER HELPERS

# This function is not supposed to throw exceptions so that it can be used
# within the main exception handler.
def writeLog(primary_disk, primary_partnum):
    try: 
        bootnode = partitionDevice(primary_disk, primary_partnum)
        primary_fs = util.TempMount(bootnode, 'install-')
        try:
            log_location = os.path.join(primary_fs.mount_point, "var/log/installer")
            if os.path.islink(log_location):
                log_location = os.path.join(primary_fs.mount_point, os.readlink(log_location).lstrip("/"))
            util.assertDir(log_location)
            xelogging.collectLogs(log_location, os.path.join(primary_fs.mount_point,"root"))
        except:
            pass
        primary_fs.unmount()
    except:
        pass

def writei18n(mounts):
    path = os.path.join(mounts['root'], 'etc/sysconfig/i18n')
    fd = open(path, 'w')
    fd.write('LANG="en_US.UTF-8"\n')
    fd.write('SYSFONT="drdos8x8"\n')
    fd.close()

def verifyRepo(media, address, ui):
    """ Check repo is accessible """
    repo_good = False
    
    if ui:
        if tui.repo.check_repo_def((media, address), True) == tui.repo.REPOCHK_NO_ERRORS:
           repo_good = True
    else:
        try:
            repos = repository.repositoriesFromDefinition(media, address)
            if len(repos) > 0:
                repo_good = True
        except:
            pass

    if not repo_good:
        raise RuntimeError, "Unable to access repository"

def getUpgrader(source):
    """ Returns an appropriate upgrader for a given source. """
    return upgrade.getUpgrader(source)

def prepareTarget(progress_callback, upgrader, *args):
    return upgrader.prepareTarget(progress_callback, *args)

def doBackup(progress_callback, upgrader, *args):
    return upgrader.doBackup(progress_callback, *args)

def prepareUpgrade(progress_callback, upgrader, *args):
    """ Gets required state from existing installation. """
    return upgrader.prepareUpgrade(progress_callback, *args)

def completeUpgrade(upgrader, *args):
    """ Puts back state into new filesystem. """
    return upgrader.completeUpgrade(*args)
