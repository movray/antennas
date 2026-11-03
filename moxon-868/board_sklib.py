from collections import defaultdict
from skidl import Pin, Part, Alias, SchLib, SKIDL, TEMPLATE

from skidl.pin import pin_types

SKIDL_lib_version = '0.0.1'

board = SchLib(tool=SKIDL).add_parts(*[
        Part(**{ 'name':'Antenna_Dipole', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'Antenna_Dipole'}), 'ref_prefix':'AE', 'fplist':[''], 'footprint':'moxon-868:Moxon_868', 'keywords':'dipole antenna', 'description':'Dipole antenna', 'datasheet':'~', 'pins':[
            Pin(num='1',name='~',func=pin_types.INPUT,unit=1),
            Pin(num='2',name='~',func=pin_types.INPUT,unit=1)], 'unit_defs':[] }),
        Part(**{ 'name':'Conn_Coaxial', 'dest':TEMPLATE, 'tool':SKIDL, 'aliases':Alias({'Conn_Coaxial'}), 'ref_prefix':'J', 'fplist':[''], 'footprint':'moxon-868:CoaxFeed_Gap2mm', 'keywords':'BNC SMA SMB SMC LEMO coaxial connector CINCH RCA MCX MMCX U.FL UMRF', 'description':'coaxial connector (BNC, SMA, SMB, SMC, Cinch/RCA, LEMO, ...)', 'datasheet':'~', 'pins':[
            Pin(num='1',name='In',func=pin_types.PASSIVE,unit=1),
            Pin(num='2',name='Ext',func=pin_types.PASSIVE,unit=1)], 'unit_defs':[] })])