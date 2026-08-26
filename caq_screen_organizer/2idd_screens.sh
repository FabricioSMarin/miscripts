#!/bin/csh
unsetenv MEDM_EXEC_LIST
unsetenv LD_LIBRARY_PATH /APSshare/caqtdm/lib
alias caQtDM "/APSshare/caqtdm/caqtdm-4.4.1/caQtDM_Binaries/rhel9-x86_64/caQtDM"

wmctrl -s 0
caQtDM -x -attach -dg +10+82 2ida_hutch.ui &
sleep 3
caQtDM -x -attach -dg +10+112 topMotors.ui &
sleep 3
caQtDM -x -attach -dg +17+987 kohzuSeqCtl_All.ui &
sleep 3
caQtDM -x -attach -dg +151+483 scaler16_full.ui &
sleep 3
caQtDM -x -attach -dg +551+947 SR570_tiny.ui &
sleep 3
caQtDM -x -attach -dg +555+1173 SR570_tiny.ui &
sleep 3
caQtDM -x -attach -dg +620+491 XIA_shutter.ui &
sleep 3
caQtDM -x -attach -dg +742+948 SR570_tiny.ui &
sleep 3
caQtDM -x -attach -dg +743+1171 SR570_tiny.ui &
sleep 3
caQtDM -x -attach -dg +931+559 2IDD_microscopeV2.ui &
sleep 3
caQtDM -x -attach -dg +1009+82 2idd_beamline.ui &
sleep 3
caQtDM -x -attach -dg +1500+578 topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +2009+82 He_levels.ui &
sleep 3

wmctrl -s 1
caQtDM -x -attach -dg +10+82 scan_full.ui &
sleep 3
caQtDM -x -attach -dg +10+792 scan_full.ui &
sleep 3
caQtDM -x -attach -dg +400+82 scan_full.ui &
sleep 3
caQtDM -x -attach -dg +400+791 scan_full.ui &
sleep 3
caQtDM -x -attach -dg +793+82 scan_full.ui &
sleep 3
caQtDM -x -attach -dg +794+790 scan_saveData.ui &
sleep 3
caQtDM -x -attach -dg +795+1088 simple_mca.ui &
sleep 3
caQtDM -x -attach -dg +1179+659 NDFileNetCDF.ui &
sleep 3
caQtDM -x -attach -dg +1184+82 mappingControl.ui &
sleep 3
caQtDM -x -attach -dg +1311+82 4element_dxp.ui &
sleep 3
caQtDM -x -attach -dg +1374+846 batchscan_v5.ui &
sleep 3
caQtDM -x -attach -dg +1890+82 SIS38XX.ui &
sleep 3

wmctrl -s 2
caQtDM -x -attach -dg +1500+82 NDFileHDF5.ui &
sleep 3
caQtDM -x -attach -dg +1508+579 ADAravis.ui &
sleep 3
