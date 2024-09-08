import time
import signal
import threading
import simplepyble
from functools import partial
from ha_mqtt_discoverable import Settings, DeviceInfo
from ha_mqtt_discoverable.sensors import Sensor, SensorInfo

OUTLET_SERVICE_UUID = '0000ff00-0000-1000-8000-00805f9b34fb'
WRITE_CHARACTERISTIC_UUID = '0000ff02-0000-1000-8000-00805f9b34fb'
NOTIFY_CHARACTERISTIC_UUID = '0000ff01-0000-1000-8000-00805f9b34fb'

ONLINE_DATA = 61441

data = {}

data_template = {
    'voltage': 0,
    'current': 0,
    'power': 0,
    'frequency': 0,
    'power_factor': 0,
    'total_consumption': 0,
    'ontime': 0,
}

mqtt_settings = Settings.MQTT(host='localhost', port=1883, username='user', password='pw')
mqtt_devices = {}

def update_devices():
    while True:
        for d_id, device in mqtt_devices.items():
            device['voltage'].set_state(data[d_id]['voltage'])
            device['current'].set_state(data[d_id]['current'])
            device['power'].set_state(data[d_id]['power'])
            device['frequency'].set_state(data[d_id]['frequency'])
            device['power_factor'].set_state(data[d_id]['power_factor'])
            device['total_consumption'].set_state(data[d_id]['total_consumption'])
        time.sleep(1)

class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        self.kill_now = True


def build_data(t):
    if t in [ONLINE_DATA, 61442, 61445, 61446, 61447, 61448]:
        n = bytearray((60308 + t).to_bytes(4))[2:4]
        for i in range(len(n)):
            n[i] ^= 0xFF
        t = t.to_bytes(2)
        o = int(4).to_bytes(2)
        ret = bytearray(8)
        ret[0:2] = int(60304).to_bytes(2)
        ret[2:4] = t
        ret[4:6] = o
        ret[6:8] = n
    elif t in [61444]:
        n = 60304 + t + 6 + 16128 + 16
        n = bytearray(n.to_bytes(4))[2:4]
        for i in range(len(n)):
            n[i] ^= 0xFF
        ret = bytearray(12)
        ret[0:2] = int(60304).to_bytes(2)
        ret[2:4] = t.to_bytes(2)
        ret[4:6] = int(6).to_bytes(2)
        ret[6:8] = int(16128).to_bytes(2)
        ret[8:10] = int(16).to_bytes(2)
        ret[10:12] = n
    return ret


def push_data(device, t):
    data = build_data(t)
    device.write_command(OUTLET_SERVICE_UUID, WRITE_CHARACTERISTIC_UUID, bytes(data))


def decrypt_data(device_identifier, data_package):
    n = int.from_bytes(data_package[0:2])
    data_type = int.from_bytes(data_package[2:4])
    s = int.from_bytes(data_package[4:6])
    if data_type == ONLINE_DATA:
        voltage = 0.001 * int.from_bytes(data_package[6:10])
        current = 0.001 * int.from_bytes(data_package[10:14])
        power = 0.001 * int.from_bytes(data_package[14:18])
        frequency = 0.1 * int.from_bytes(data_package[18:20])
        power_factor = 0.01 * int.from_bytes(data_package[20:22])
        total_consumption = 0.001 * int.from_bytes(data_package[22:26])
        ontime = int.from_bytes(data_package[26:30])
        data[device_identifier]['voltage'] = voltage
        data[device_identifier]['current'] = current
        data[device_identifier]['power'] = power
        data[device_identifier]['frequency'] = frequency
        data[device_identifier]['power_factor'] = power_factor
        data[device_identifier]['total_consumption'] = total_consumption
        data[device_identifier]['ontime'] = ontime


def main():
    # pick the first bluetooth adapter
    adapters = simplepyble.Adapter.get_adapters()
    if len(adapters) == 0:
        print('No bluetooth adapters found')
        return
    adapter = adapters[0]

    # scan devices
    avail_devices = []
    while len(avail_devices) == 0:
        adapter.scan_for(5000)
        peripherals = adapter.scan_get_results()
        for peripheral in peripherals:
            services = peripheral.services()
            if len(services) > 0:
                for service in services:
                    service_uuid = service.uuid()
                    if service_uuid.upper() == OUTLET_SERVICE_UUID.upper():
                        avail_devices.append(peripheral)
                        break

    # setup job
    for avail_device in avail_devices:
        # connect to devices found
        while not avail_device.is_connected():
            avail_device.connect()
            time.sleep(1)

        # create data structure
        data[avail_device.identifier()] = data_template.copy()

        # register notification
        avail_device.notify(OUTLET_SERVICE_UUID, NOTIFY_CHARACTERISTIC_UUID, partial(decrypt_data, avail_device.identifier()))

        # create mqtt devices
        d_id = avail_device.identifier()
        device_info = DeviceInfo(name=f'Outlet - {d_id}', identifiers=('Outlet', d_id))
        
        voltage_sensor_info = SensorInfo(name='Voltage', device_class='voltage', unique_id=f'V{d_id}', unit_of_measurement='V', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=voltage_sensor_info)
        voltage_sensor = Sensor(settings)

        current_sensor_info = SensorInfo(name='Current', device_class='current', unique_id=f'C{d_id}', unit_of_measurement='A', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=current_sensor_info)
        current_sensor = Sensor(settings)

        power_sensor_info = SensorInfo(name='Power', device_class='power', unique_id=f'P{d_id}', unit_of_measurement='W', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=power_sensor_info)
        power_sensor = Sensor(settings)

        frequency_sensor_info = SensorInfo(name='Frequency', device_class='frequency', unique_id=f'F{d_id}', unit_of_measurement='Hz', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=frequency_sensor_info)
        frequency_sensor = Sensor(settings)

        power_factor_sensor_info = SensorInfo(name='Power Factor', device_class='power_factor', unique_id=f'PF{d_id}', unit_of_measurement='', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=power_factor_sensor_info)
        power_factor_sensor = Sensor(settings)

        total_consumption_sensor_info = SensorInfo(name='Total Consumption', device_class='energy', unique_id=f'TC{d_id}', unit_of_measurement='kWh', device=device_info)
        settings = Settings(mqtt=mqtt_settings, entity=total_consumption_sensor_info)
        total_consumption_sensor = Sensor(settings)

        mqtt_devices[d_id] = {
            'voltage': voltage_sensor,
            'current': current_sensor,
            'power': power_sensor,
            'frequency': frequency_sensor,
            'power_factor': power_factor_sensor,
            'total_consumption': total_consumption_sensor
        }

    # start updating devices
    threading.Thread(target=update_devices, daemon=True).start()

    killer = GracefulKiller()
    while not killer.kill_now:
        # build and write
        for avail_device in avail_devices:
            push_data(avail_device, ONLINE_DATA)
        time.sleep(1)

    for avail_device in avail_devices:
        avail_device.disconnect()


if __name__ == "__main__":
    main()
