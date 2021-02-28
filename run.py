#!/usr/bin/env python3

import json
import struct
import time
import re
import dbus
import dbus.mainloop.glib
from gi.repository import GObject as gobject
from influxdb import InfluxDBClient

#
# Configuration
config=json.load(open('config.json'))

#
# Initialize DBus
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
mainloop = gobject.MainLoop()
bus=dbus.SystemBus()

#
# Initialize InfluxDB Client

dbclient = InfluxDBClient(config['influxdb']['host'], config['influxdb']['port'], config['influxdb']['user'], config['influxdb']['password'], config['influxdb']['database'])

#
# Import list of known GATT variables
gatt_database=json.load(open('gatt-database.json'))
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

#
# Find all available variables
characteristics=[]
mngr=bus.get_object('org.bluez','/')
re_char=re.compile('/org/bluez/hci0/dev_[0-9A-Z_]+/service[0-9a-z]+/char[0-9a-z]+$')
for obj in filter(lambda obj: re_char.match(obj), mngr.GetManagedObjects(dbus_interface='org.freedesktop.DBus.ObjectManager')):
    obj=bus.get_object('org.bluez', obj)
    
    # Check if this is a known characteristic
    UUID=obj.Get('org.bluez.GattCharacteristic1', 'UUID', dbus_interface='org.freedesktop.DBus.Properties')
    filt=filter(lambda char: char['uuid']==UUID, known_characteristics)
    try:
        info=next(filt).copy()
    except StopIteration:
        continue

    # Build up information about this characteristic
    info['obj']=obj

    Service=obj.Get('org.bluez.GattCharacteristic1', 'Service', dbus_interface='org.freedesktop.DBus.Properties')
    Service=bus.get_object('org.bluez', Service)
    info['Service']=Service
    info['ServiceUUID']=Service.Get('org.bluez.GattService1','UUID',dbus_interface='org.freedesktop.DBus.Properties')
    
    Device=Service.Get('org.bluez.GattService1', 'Device', dbus_interface='org.freedesktop.DBus.Properties')
    Device=bus.get_object('org.bluez', Device)
    info['Device']=Device

    # Determine device information
    info['DeviceName']=Device.Get('org.bluez.Device1','Name'   ,dbus_interface='org.freedesktop.DBus.Properties')
    info['DeviceMAC' ]=Device.Get('org.bluez.Device1','Address',dbus_interface='org.freedesktop.DBus.Properties')

    characteristic=GATTMonitor(dbclient, obj,
                                   info['uuid'], info['name'], info['type'],
                                   info['ServiceUUID'],
                                   info['DeviceName'], info['DeviceMAC'])
print('---')

#
# Monitoring loop

mainloop.run()
