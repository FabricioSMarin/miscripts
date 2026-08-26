#!/bin/csh
unsetenv MEDM_EXEC_LIST
unsetenv LD_LIBRARY_PATH /APSshare/caqtdm/lib
alias caQtDM "/APSshare/caqtdm/caqtdm-4.4.1/caQtDM_Binaries/rhel9-x86_64/caQtDM"


wmctrl -s 0

wmctrl -s 1

wmctrl -s 2

wmctrl -s 3
