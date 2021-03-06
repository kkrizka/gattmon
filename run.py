#!/usr/bin/env python3

import json
import struct
import re
import os, sys

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

from influxdb import InfluxDBClient

#
# Setup
myloc=os.path.dirname(sys.argv[0])

#
# Configuration
config=json.load(open(f'{myloc}/config.json'))

#
# Initialize DBus
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
mainloop = GLib.MainLoop()
bus=dbus.SystemBus()

#
# Initialize InfluxDB Client

dbclient = InfluxDBClient(config['influxdb']['host'], config['influxdb']['port'], config['influxdb']['user'], config['influxdb']['password'], config['influxdb']['database'])

#
# Import list of known GATT variables
gatt_database=json.load(open(f'{myloc}/gatt-database.json'))
known_characteristics=gatt_database['characteristics']

class GATTMonitor:
    def __init__(self,dbclient, bus_obj, uuid, name, vtype, service_uuid, device_name, device_mac):
        self.dbclient=dbclient
        self.bus_obj=bus_obj

        # My information
        self.uuid=uuid
        self.name=name
        self.vtype=vtype

        # Service information
        self.service_uuid=service_uuid

        # Device information
        self.device_name=device_name
        self.device_mac =device_mac

        #
        # Setup notifications
        bus_obj.connect_to_signal("PropertiesChanged", self.log)
        bus_obj.StartNotify(dbus_interface='org.bluez.GattCharacteristic1')

        #
        # Setup template for point
        self.point={
            "measurement": "GATT",
            "tags": {
                "char_uuid"   : self.uuid,
                "char_name"   : self.name,
                "service_uuid": self.service_uuid,
                "device_name" : self.device_name,
                "device_mac"  : self.device_mac,
                },
            "fields": {}
            }
        
    def log(self, interface, properties, invalidated_properties):
        if 'Value' not in properties:
            return # Some are empty
        value=struct.unpack(self.vtype,bytes(properties['Value']))[0]
        print(self.name,value)
        point=self.point.copy()
        point['fields']
        point['fields']['value']=value
        self.dbclient.write_points([point])

class CharacteristicManager:
    def __init__(self, bus):
        self.bus=bus

        self.characteristics={}

        self.re_char=re.compile('/org/bluez/hci0/dev_[0-9A-Z_]+/service[0-9a-z]+/char[0-9a-z]+$')

        #
        # Find services
        mngr=bus.get_object('org.bluez','/')

        # Add existing services
        for obj in filter(lambda obj: self.re_char.match(obj),mngr.GetManagedObjects(dbus_interface='org.freedesktop.DBus.ObjectManager')):
            self.add_monitor(obj)
            
        # Monitor for new services
        mngr.connect_to_signal("InterfacesAdded"  , self.InterfacesAdded)

    def InterfacesAdded(self, path, interfaces):
        if not self.re_char.match(path): return
        self.add_monitor(path)

    def add_monitor(self, path):
        if path in characteristics:
            print(f'Already monitoring {path}')
            return

        print(f'Adding characteristic at {path}')
        obj=self.bus.get_object('org.bluez', path)
    
        # Check if this is a known characteristic
        UUID=obj.Get('org.bluez.GattCharacteristic1', 'UUID', dbus_interface='org.freedesktop.DBus.Properties')
        filt=filter(lambda char: char['uuid']==UUID, known_characteristics)
        try:
            info=next(filt).copy()
        except StopIteration:
            return

        # Build up information about this characteristic
        info['obj']=obj

        Service=obj.Get('org.bluez.GattCharacteristic1', 'Service', dbus_interface='org.freedesktop.DBus.Properties')
        Service=self.bus.get_object('org.bluez', Service)
        info['Service']=Service
        info['ServiceUUID']=Service.Get('org.bluez.GattService1','UUID',dbus_interface='org.freedesktop.DBus.Properties')
    
        Device=Service.Get('org.bluez.GattService1', 'Device', dbus_interface='org.freedesktop.DBus.Properties')
        Device=self.bus.get_object('org.bluez', Device)
        info['Device']=Device

        # Determine device information
        info['DeviceName']=Device.Get('org.bluez.Device1','Name'   ,dbus_interface='org.freedesktop.DBus.Properties')
        info['DeviceMAC' ]=Device.Get('org.bluez.Device1','Address',dbus_interface='org.freedesktop.DBus.Properties')

        characteristic=GATTMonitor(dbclient, obj,
                                   info['uuid'], info['name'], info['type'],
                                   info['ServiceUUID'],
                                   info['DeviceName'], info['DeviceMAC'])
        self.characteristics[path]=characteristic

        return characteristic
        
#
# Find all available variables
characteristics=[]
mngr=CharacteristicManager(bus)

#
# Monitoring loop
print('Starting main loop')
mainloop.run()
