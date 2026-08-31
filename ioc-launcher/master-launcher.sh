#!/usr/bin/env bash
# master launcher script — also the IOC inventory for ioc_control_gui.py
#
# SSH identity model (multi-user):
#   - Always use the *local* account's private key: ~/.ssh/ioc_launcher
#   - Do NOT point -i at another user's ~/.ssh (Permission denied).
#   - Remote user@host is whoever owns/started that IOC (may differ from local user).
#
# Authorize a new local GUI user for all IOC hosts below:
#   1. As that local user:
#        mkdir -p ~/.ssh && chmod 700 ~/.ssh
#        ssh-keygen -t ed25519 -f ~/.ssh/ioc_launcher -N ""
#   2. Append ~/.ssh/ioc_launcher.pub to authorized_keys for EACH remote
#      account used below (currently: user2idd, user2ide, userbnp, user8bmb)
#      on the matching host(s).
#   3. Test:
#        ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
#          <remote_user>@<host> hostname

# --- coeus ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2idd@coeus.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/2idbleps/iocBoot/ioc2idbleps/softioc/2idbleps.pl start"

ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2idd@coeus.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/2idsft/iocBoot/ioc2idsft/softioc/2idsft.pl start"

ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2idd@coeus.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/2idBPM/iocBoot/iocbpm/2idBPM.sh start"

# --- 2iddnx ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2idd@2iddnx.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/2iddfS1/iocBoot/ioc2iddfS1/softioc/2iddfS1.pl start"

ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2idd@2iddnx.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/2iddVLM/iocBoot/ioc2iddVLM/softioc/2iddVLM.pl start"

# --- 2idenx ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user2ide@2idenx.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/2xfmS1/iocBoot/ioc2xfmS1/softioc/2xfmS1.pl start"

# --- cactus ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  userbnp@cactus-priv.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/bnpxspress3/iocBoot/iocbnpxspress3/softioc/bnpxspress3.pl start"

# --- clover ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  userbnp@clover.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/bnpsft/iocBoot/iocbnpsft/softioc/bnpsft.pl start"

# --- 8bmfd1 ---
ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user8bmb@8bmfd1.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/8bmbsft/iocBoot/ioc8bmbsft/softioc/8bmbsft.pl start"

ssh -i ~/.ssh/ioc_launcher -o BatchMode=yes -o IdentitiesOnly=yes \
  user8bmb@8bmfd1.xray.aps.anl.gov \
  "/net/s2dserv/xorApps/epics/synApps_6_3/ioc/xspress3/iocBoot/iocxspress3/softioc/xspress3.pl start"
