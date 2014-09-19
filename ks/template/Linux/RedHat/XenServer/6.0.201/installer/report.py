#!/usr/bin/env python
# Copyright (c) Citrix Systems 2010.  All rights reserved.
# Xen, the Xen logo, XenCenter, XenMotion are trademarks or registered
# trademarks of Citrix Systems, Inc., in the United States and other
# countries.

import diskutil
import ftplib
import os.path
import netutil
import tui
import tui.network
import snack
import snackutil
import sys
import uicontroller
import urlparse
import util
from version import *
from xelogging import collectLogs

import xcp.accessor
import xcp.logger as xelogging


def selectDefault(key, entries):
    """ Given a list of (text, key) and a key to select, returns the appropriate
    text,key pair, or None if not in entries. """

    for text, k in entries:
        if key == k:
            return text, k
    return None

def select_report_media(answers):
    ENTRY_LOCAL = 'Local media', 'local'
    ENTRY_URL = 'FTP', 'ftp'
    ENTRY_NFS = 'NFS', 'nfs'
    entries = [ ENTRY_LOCAL ]

    default = ENTRY_LOCAL
    if len(answers['network-hardware'].keys()) > 0:
        entries += [ ENTRY_URL, ENTRY_NFS ]

        # default selection?
        if 'dest-media' in answers:
            default = selectDefault(answers['dest-media'], entries)

    (button, entry) = snack.ListboxChoiceWindow(
        tui.screen,
        "Save Report",
        "Select where to store report.",
        entries,
        ['Ok', 'Back'], default=default, help = 'selrepdst'
        )

    if button == 'back': return uicontroller.LEFT_BACKWARDS

    # clear the dest-address key?
    if 'dest-media' in answers and answers['dest-media'] != entry:
        answers['dest-address'] = ""

    # store their answer:
    answers['dest-media'] = entry

    return uicontroller.RIGHT_FORWARDS

def disk_more_info(context):
    if not context: return True

    usage = 'unknown'
    (boot, state, storage) = diskutil.probeDisk(context)
    if boot[0]:
        usage = "%s installation" % (PRODUCT_BRAND or PLATFORM_NAME)
    elif storage[0]:
        usage = 'VM storage'

    tui.update_help_line([' ', ' '])
    snackutil.TableDialog(tui.screen, "Details", ("Disk:", diskutil.getHumanDiskName(context)),
                          ("Vendor:", diskutil.getDiskDeviceVendor(context)),
                          ("Model:", diskutil.getDiskDeviceModel(context)),
                          ("Size:", diskutil.getHumanDiskSize(diskutil.getDiskDeviceSize(context))),
                          ("Current usage:", usage))
    tui.screen.popHelpLine()
    return True

def get_local_disk(answers):
    diskEntries = diskutil.getQualifiedDiskList()

    entries = []
    target_is_sr = {}
    
    for de in diskEntries:
        (vendor, model, size) = diskutil.getExtendedDiskInfo(de)
        # determine current usage
        target_is_sr[de] = False
        (boot, state, storage) = diskutil.probeDisk(de)
        if storage[0]:
            target_is_sr[de] = True
        (vendor, model, size) = diskutil.getExtendedDiskInfo(de)
        stringEntry = "%s - %s [%s %s]" % (diskutil.getHumanDiskName(de), diskutil.getHumanDiskSize(size), vendor, model)
        e = (stringEntry, de)
        entries.append(e)

    # default value:
    default = None
    if 'dest-disk' in answers:
        default = selectDefault(answers['dest-disk'], entries)

    tui.update_help_line([None, "<F5> more info"])

    scroll, height = snackutil.scrollHeight(4, len(entries))
    (button, entry) = snackutil.ListboxChoiceWindowEx(
        tui.screen,
        "Select Device",
        "Please select the device to store the report on.",
        entries,
        ['Ok', 'Back'], 55, scroll, height, default, help = 'getlocaldisk:info',
        hotkey = 'F5', hotkey_cb = disk_more_info)

    tui.screen.popHelpLine()

    if button == 'back': return uicontroller.LEFT_BACKWARDS

    # entry contains the 'de' part of the tuple passed in
    answers['dest-disk'] = entry

    return uicontroller.RIGHT_FORWARDS

def get_local_dest(answers):
    partitions = diskutil.partitionsOnDisk(answers['dest-disk'])

    if len(partitions) == 0:
        answers['dest-address'] = answers['dest-disk']
    elif len(partitions) == 1:
        answers['dest-address'] = '/dev/' + partitions[0]
    else:
        entries = []
    
        for part in partitions:
            e = (part, '/dev/' + part)
            entries.append(e)

        # default value:
        default = None
        if 'dest-address' in answers:
            default = selectDefault(answers['dest-address'], entries)

        tui.update_help_line([None, "<F5> more info"])

        scroll, height = snackutil.scrollHeight(4, len(entries))
        (button, entry) = snackutil.ListboxChoiceWindowEx(
            tui.screen,
            "Select Device",
            "Please select the partition to store the report on.",
            entries,
            ['Ok', 'Back'], 55, scroll, height, default, help = 'getlocaldest:info',
            hotkey = 'F5', hotkey_cb = disk_more_info)

        tui.screen.popHelpLine()

        if button == 'back': return uicontroller.LEFT_BACKWARDS

        # entry contains the 'de' part of the tuple passed in
        answers['dest-address'] = entry

    return uicontroller.RIGHT_FORWARDS


def get_ftp_dest(answers):
    text = "Please enter the URL for your FTP directory and, optionally, a username and password"
    url_field = snack.Entry(50)
    user_field = snack.Entry(16)
    passwd_field = snack.Entry(16, password = 1)
    url_text = snack.Textbox(11, 1, "URL:")
    user_text = snack.Textbox(11, 1, "Username:")
    passwd_text = snack.Textbox(11, 1, "Password:")

    if 'dest-address' in answers:
        url = answers['dest-address']
        (scheme, netloc, path, params, query) = urlparse.urlsplit(url)
        (hostname, username, password) = util.splitNetloc(netloc)
        if username != None:
            user_field.set(username)
            if password == None:
                url_field.set(url.replace('%s@' % username, '', 1))
            else:
                passwd_field.set(password)
                url_field.set(url.replace('%s:%s@' % (username, password), '', 1))
        else:
            url_field.set(url)

    gf = snack.GridFormHelp(tui.screen, "Specify Path", 'getftpdest', 1, 3)
    bb = snack.ButtonBar(tui.screen, [ 'Ok', 'Back' ])
    t = snack.TextboxReflowed(50, text)

    entry_grid = snack.Grid(2, 3)
    entry_grid.setField(url_text, 0, 0)
    entry_grid.setField(url_field, 1, 0)
    entry_grid.setField(user_text, 0, 1)
    entry_grid.setField(user_field, 1, 1, anchorLeft = 1)
    entry_grid.setField(passwd_text, 0, 2)
    entry_grid.setField(passwd_field, 1, 2, anchorLeft = 1)

    gf.add(t, 0, 0, padding = (0, 0, 0, 1))
    gf.add(entry_grid, 0, 1, padding = (0, 0, 0, 1))
    gf.add(bb, 0, 2, growx = 1)

    button = bb.buttonPressed(gf.runOnce())

    if button == 'back': return uicontroller.LEFT_BACKWARDS

    url = url_field.value()
    if not url.startswith('ftp://'):
        url = 'ftp://' + url
    if user_field.value() != '':
        if passwd_field.value() != '':
            answers['dest-address'] = url.replace('//', '//%s:%s@' % (user_field.value(), passwd_field.value()), 1)
        else:
            answers['dest-address'] = url.replace('//', '//%s@' % user_field.value(), 1)
    else:
        answers['dest-address'] = url
            
    return uicontroller.RIGHT_FORWARDS

def get_nfs_dest(answers):
    text = "Please enter the server and path of your NFS share (e.g. myserver:/my/directory)"
    label = "NFS Path:"
        
    if 'dest-address' in answers:
        default = answers['dest-address']
    else:
        default = ""
    (button, result) = snack.EntryWindow(
        tui.screen,
        "Specify Path",
        text,
        [(label, default)], entryWidth = 50, width = 50,
        buttons = ['Ok', 'Back'], help = 'getnfsdest')
            
    if button == 'back': return uicontroller.LEFT_BACKWARDS

    answers['dest-address'] = result[0]

    return uicontroller.RIGHT_FORWARDS

def select_report_dest(answers):
    if answers['dest-media'] == 'local':
        return get_local_dest(answers)
    elif answers['dest-media'] == 'ftp':
        return get_ftp_dest(answers)
    elif answers['dest-media'] == 'nfs':
        return get_nfs_dest(answers)

def report_complete(report_saved):
    if report_saved:
        snack.ButtonChoiceWindow(tui.screen,
                                 "Report Saved",
                                 "Report saved successfully.", 
                                 ['Ok'])
    else:
        snack.ButtonChoiceWindow(tui.screen,
                                 "Error",
                                 "Unable to save report.", 
                                 ['Ok'])

    return uicontroller.RIGHT_FORWARDS


def main(args):
    results = {}
    dests = []
    ui = None

    xelogging.openLog('/dev/tty3')

    if len(args) == 0:
        ui = tui
    else:
        dests = args
        
    if ui:
        ui.init_ui()

        results['network-hardware'] = netutil.scanConfiguration()

        local_dest = lambda a: a['dest-media'] == 'local'
        remote_dest = lambda a: a['dest-media'] != 'local'

        seq = [
            uicontroller.Step(select_report_media),
            uicontroller.Step(tui.network.requireNetworking, predicates = [remote_dest]),
            uicontroller.Step(get_local_disk, predicates = [local_dest]),
            uicontroller.Step(select_report_dest),
            ]
        rc = uicontroller.runSequence(seq, results)
        if rc == uicontroller.RIGHT_FORWARDS:
            xelogging.log("ANSWERS DICTIONARY:")
            xelogging.log(str(results))

            if results['dest-media'] == 'local':
                dests.append("dev://" + results['dest-address'])
            elif results['dest-media'] == 'ftp':
                dests.append(results['dest-address'])
            elif results['dest-media'] == 'nfs':
                dests.append("nfs://" + results['dest-address'])

    # create tarball
    collectLogs('/tmp', '/tmp')

    report_saved = False
    for dest in dests:
        xelogging.log("Saving report to: " + dest)
        try:
            a = xcp.accessor.createAccessor(dest, False)
            a.start()
            fh = open('/tmp/support.tar.bz2')
            a.writeFile(fh, 'support.tar.bz2')
            fh.close()
            a.finish()
            report_saved = True
        except Exception, e:
            xelogging.log("Failed: " + str(e))
            report_saved = False

    if ui:
        if rc == uicontroller.RIGHT_FORWARDS:
            report_complete(report_saved)
        ui.end_ui()

if __name__ == "__main__":
    main(sys.argv[1:])
