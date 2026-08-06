#!/bin/csh
unsetenv MEDM_EXEC_LIST
# Changed for linux platform 5/15/09 DCC
unsetenv LD_LIBRARY_PATH /APSshare/caqtdm/lib
#/APSshare/epics/base-3.14.12.3/lib/linux-x86_64

export EPICS_CA_ADDR_LIST "10.54.113.255 164.54.113.168"


alias caQtDM "/APSshare/caqtdm/caqtdm-4.4.1/caQtDM_Binaries/rhel9-x86_64/caQtDM"

if ($1 == 1) then
#wmctrl -s 0

wmctrl -s 1
caQtDM -x -attach -dg +60+0 -macro "P=2xfm:,S=scaler1" scaler_full.ui &
sleep 3
caQtDM -x -attach -dg +60+325 -macro "P=2xfm:,S=scaler2" scaler_full.ui &
sleep 3
caQtDM -x -attach -dg +1135+0 -macro "P=2xfm:,S=scaler3" scaler32_full.ui &
sleep 3
caQtDM -x -attach -dg +0+1300 -macro "P=2xfm:,M1=m1,M2=m2,M3=m3,M4=m4,M5=m5,M6=m6,M7=m7,M8=m8" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +155+1300 -macro "P=2xfm:,M1=m9,M2=m10,M3=m11,M4=m12,M5=m13,M6=m14,M7=m15,M8=m16" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +310+1300 -macro "P=2xfm:,M1=m17,M2=m18,M3=m19,M4=m20,M5=m21,M6=m22,M7=m23,M8=m24" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +465+1300 -macro "P=2xfm:,M1=m25,M2=m26,M3=m27,M4=m28,M5=m29,M6=m30,M7=m31,M8=m32" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +620+1300 -macro "P=2xfm:,M1=m33,M2=m34,M3=m35,M4=m36,M5=m37,M6=m38,M7=m39,M8=m40" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +775+1300 -macro "P=2xfm:,M1=m49,M2=m50,M3=m51,M4=m52,M5=m53,M6=m54,M7=m55,M8=m56" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +930+1300 -macro "P=2xfm:,M1=m57,M2=m58,M3=m59,M4=m60,M5=m61,M6=m62,M7=m63,M8=m64" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +1085+1300 -macro "P=2xfm:,M1=m65,M2=m66,M3=m67,M4=m68,M5=m69,M6=m70,M7=m71,M8=m72" topMotors8.ui &
sleep 3
caQtDM -x -attach -dg +1240+1300 -macro "P=2xfm:,M1=m200,M2=m201" topMotors8.ui &
sleep 3
caQtDM -attach -x -dg +5+550 -macro "xx=02us" UndulatorCtl.ui &
sleep 3
caQtDM -attach -x -dg +350+550 -macro "xx=02ds" UndulatorCtl.ui &
sleep 3
caQtDM -attach -x -dg +575+550  2id_ID_BPM.ui &
sleep 3
caQtDM -attach -x -dg +1200+550 -macro "s=02" beamHistory_full.ui &
sleep 3
caQtDM -attach -x -dg +480+5 2ida_hutch.ui
sleep 3

wmctrl -s 2
caQtDM -attach -x -dg +5+1000 -macro "P=2xfm:,N=1,S=scan1,DW=Dwait1,PW=Pwait1" scan_full.ui &
sleep 3
caQtDM -attach -x -dg +395+1000 -macro "P=2xfm:,N=2,S=scan2,DW=Dwait2,PW=Pwait2" scan_full.ui &
sleep 3
caQtDM -attach -x -dg +5+5 -macro "P=2xfm:F,N=1,S=scanH,DW=Dwait1,PW=Pwait1" scan_full.adl &
sleep 3
caQtDM -attach -x -dg +395+5 -macro "P=2xfm:F,N=2,S=scan1,DW=Dwait1,PW=Pwait1" scan_full.adl &
sleep 3
caQtDM -x -attach -dg +40+450 -macro "P=2xfm:" 2ide_scan_setup.ui &
sleep 3
caQtDM -x -attach -dg +800+100 -macro "P=2xfm:,B=1" batchscan_v5.ui &
sleep 3
caQtDM -x -attach -dg +680+500 -macro "P=2xfm:" 2ide_microscope_new.ui &
sleep 3
caQtDM -x -attach -dg +680+500 -macro "P=2xfm:" FlyScanSetupSmall_V2.ui &
sleep 3
caQtDM -attach -x -dg +1500+5 2xfm_beamline.ui &
sleep 3

wmctrl -s 3
caQtDM -x -attach -dg +10+10 -macro "P=2xfm:mcs:" SIS38XX.ui &
sleep 3
caQtDM -x -attach -dg +10+600 -macro "P=dxpXMAP2xfm3:,D=dxp,M=mca" 4element_dxp.ui &
sleep 3
caQtDM -x -attach -dg +600+600 -macro "P=dxpXMAP2xfm3:" mappingControl.ui & 
sleep 3
caQtDM -x -attach -dg +1100+600 -macro "P=dxpXMAP2xfm3:,R=netCDF1:" NDFileNetCDF.ui &
sleep 3
caQtDM -x -attach -dg +700+0 -macro "P=dxpXMAP2xfm3:mca,M=1" simple_mca.ui &
sleep 3
caQtDM -x -attach -dg +1150+0 -macro "P=dxpXMAP2xfm3:mca,M=2" simple_mca.ui &
sleep 3
caQtDM -x -attach -dg +1600+0 -macro "P=dxpXMAP2xfm3:mca,M=3" simple_mca.ui &
sleep 3
caQtDM -x -attach -dg +2050+0 -macro "P=dxpXMAP2xfm3:mca,M=4" simple_mca.ui &
sleep 3
caQtDM -x -attach -dg +2050+0 -macro "P=2ideXS1" xspress3_4chan.ui &
sleep 3


else if ($1 == 2) then 
caQtDM -attach -x -dg +1500+5 2xfm_beamline.ui &

endif