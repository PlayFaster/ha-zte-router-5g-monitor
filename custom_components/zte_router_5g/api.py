import requests
import hashlib
import binascii
import urllib3
import json
import time
from datetime import datetime
from requests.exceptions import RequestException

# Suppress SSL warnings for local router access
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class ZTERouterAPI:
    def __init__(self, ip, username, password):
        self.ip = ip
        self.username = username
        self.password = password
        self.protocol = "http"
        self.session = requests.Session()
        self.session.verify = False
        self.referer = f"http://{self.ip}/"
        self.timeout = 15 # Default timeout for standard polling
        self.stok = None

    def _hash(self, val):
        if val is None:
            raise ValueError("Input to hash function cannot be None")
        return hashlib.sha256(val.encode()).hexdigest()

    def _hex_decode(self, hex_str):
        if not hex_str: return ""
        decoded = ""
        try:
            for i in range(0, len(hex_str), 4):
                decoded += chr(int(hex_str[i:i+4], 16))
            return decoded
        except Exception:
            return "[Decoding Error]"

    def _parse_date(self, date_str):
        if not date_str: return None
        try:
            parts = date_str.split(',')
            if len(parts) >= 6:
                year = int(f"20{parts[0]}")
                month = int(parts[1])
                day = int(parts[2])
                hour = int(parts[3])
                minute = int(parts[4])
                second = int(parts[5])
                dt = datetime(year, month, day, hour, minute, second)
                return dt.isoformat()
        except: pass
        return date_str

    def try_set_protocol(self, timeout=5):
        """Identify if router is on http or https with a short timeout."""
        protocols = ["http", "https"]
        for proto in protocols:
            url = f"{proto}://{self.ip}"
            try:
                r = self.session.get(url, timeout=timeout)
                if r.ok:
                    self.protocol = proto
                    self.referer = f"{self.protocol}://{self.ip}/"
                    return
            except: pass

    def get_version(self, timeout=None):
        tout = timeout or self.timeout
        url = f"{self.referer}goform/goform_get_cmd_process?isTest=false&cmd=wa_inner_version"
        try:
            r = self.session.get(url, headers={"Referer": self.referer}, timeout=tout)
            return r.json().get("wa_inner_version", "")
        except: return ""

    def get_LD(self, timeout=None):
        tout = timeout or self.timeout
        url = f"{self.referer}goform/goform_get_cmd_process?isTest=false&cmd=LD"
        try:
            r = self.session.get(url, headers={"Referer": self.referer}, timeout=tout)
            return r.json().get("LD", "").upper()
        except Exception as e:
            raise Exception(f"Failed to get LD token: {e}")

    def login(self, timeout=None):
        """Clean login that resets the internal session state."""
        tout = timeout or self.timeout
        self.stok = None
        self.session.cookies.clear()
        
        ld = self.get_LD(timeout=tout)
        version = self.get_version(timeout=tout)
        
        if not self.password: raise Exception("No password provided")
        pass_hash = self._hash(self.password).upper()
        zte_pass = self._hash(pass_hash + ld).upper()
        
        is_multi = True
        if version and any(m in version for m in ['MC801', 'MC7010']):
            is_multi = False

        payload = {
            'isTest': 'false',
            'goformId': 'LOGIN' if (self.username and not is_multi) else 'LOGIN_MULTI_USER',
            'password': zte_pass
        }
        if self.username: payload['username'] = self.username
        
        r = self.session.post(f"{self.referer}goform/goform_set_cmd_process", data=payload, headers={"Referer": self.referer}, timeout=tout)
        stok = r.cookies.get("stok", "").strip('\"')
        if not stok: raise Exception("Login failed")
        self.stok = f"stok={stok}"
        return self.stok

    def get_all_data(self):
        """Fetch primary technical data."""
        if not self.stok: self.login()
        
        params = [
            "cell_id", "lan_ipaddr", "lte_ca_pcell_band", "lte_ca_pcell_bandwidth",
            "lte_ca_scell_band", "lte_ca_scell_bandwidth", "lte_pci", "lte_rsrp",
            "lte_rsrq", "lte_rssi", "lte_snr", "mdm_mcc", "mdm_mnc", "monthly_rx_bytes",
            "monthly_tx_bytes", "network_provider", "network_type", "nr5g_action_band",
            "nr5g_action_channel", "nr5g_pci", "realtime_time", "rmcc", "rmnc", 
            "signalbar", "wan_active_band", "wan_active_channel", "wan_apn", 
            "wan_connect_status", "wan_ipaddr", "wan_lte_ca", "wa_inner_version", 
            "Z5g_rsrp", "Z5g_SINR", "rssi", "rscp", "sms_unread_num", "sms_received_flag",
            "sms_nv_rev_total", "sms_nv_send_total", "sms_nv_draftbox_total",
            "sms_sim_rev_total", "sms_sim_send_total", "sms_sim_draftbox_total",
            "sms_nv_total", "sms_sim_total"
        ]
        cmd = ",".join(params)
        url = f"{self.referer}goform/goform_get_cmd_process?multi_data=1&isTest=false&sms_received_flag_flag=0&cmd={cmd}"
        headers = {"Referer": f"{self.referer}index.html", "Cookie": self.stok}
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            data = response.json()
            # Session expired check
            if data.get("network_type") == "" and data.get("signalbar") == "":
                self.login()
                return self.get_all_data()
            return data
        except:
            self.stok = None
            raise

    def get_sms_capacity(self):
        if not self.stok: self.login()
        url = f"{self.referer}goform/goform_get_cmd_process?isTest=false&cmd=sms_capacity_info"
        headers = {"Referer": f"{self.referer}index.html", "Cookie": self.stok}
        try:
            r = self.session.get(url, headers=headers, timeout=self.timeout)
            return r.json()
        except: return {}

    def get_last_sms_content(self):
        if not self.stok: self.login()
        url = f"{self.referer}goform/goform_get_cmd_process"
        payload = {"isTest": "false", "cmd": "sms_data_total", "page": "0", "data_per_page": "1", "mem_store": "1", "tags": "10", "order_by": "order by id desc"}
        headers = {"Referer": f"{self.referer}index.html", "Cookie": self.stok}
        try:
            r = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
            messages = r.json().get("messages", [])
            if messages:
                msg = messages[0]
                msg["content_decoded"] = self._hex_decode(msg.get("content", ""))
                msg["number_decoded"] = self._hex_decode(msg.get("number", ""))
                msg["date_decoded"] = self._parse_date(msg.get("date", ""))
                return msg
            return {}
        except: return {}

    def reboot(self):
        """Execute a device reboot using string-based payload. Confirmed working."""
        try:
            self.login() 
            ad = self.get_AD()
            payload = f'isTest=false&goformId=REBOOT_DEVICE&AD={ad}'
            headers = {
                "Referer": self.referer, 
                "Cookie": self.stok,
                "Content-Type": "application/x-www-form-urlencoded"
            }
            r = self.session.post(f"{self.referer}goform/goform_set_cmd_process", headers=headers, data=payload, timeout=self.timeout)
            return r.status_code
        except Exception:
            self.stok = None
            raise

    def delete_sms(self, msg_id):
        """Helper to delete SMS using specific session. Use delete_all_sms for button action."""
        if not self.stok: self.login()
        ad = self.get_AD()
        payload = f'isTest=false&goformId=DELETE_SMS&msg_id={msg_id}&AD=' + ad
        headers = {
            "Referer": self.referer, 
            "Cookie": self.stok,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        r = self.session.post(f"{self.referer}goform/goform_set_cmd_process", headers=headers, data=payload, timeout=self.timeout)
        return r.status_code

    def delete_all_sms(self):
        """
        Action Button Logic:
        1. Force a clean login (robustness).
        2. Fetch the latest IDs (the "Read").
        3. Trigger the deletion (the "Write").
        """
        try:
            # Step 1: Force a fresh session
            self.login()
            
            # Step 2: Robust Read
            url = f"{self.referer}goform/goform_get_cmd_process"
            payload = {"isTest": "false", "cmd": "sms_data_total", "page": "0", "data_per_page": "500", "mem_store": "1", "tags": "10", "order_by": "order by id desc"}
            headers = {"Referer": f"{self.referer}index.html", "Cookie": self.stok}
            r = self.session.post(url, data=payload, headers=headers, timeout=self.timeout)
            ids = [m['id'] for m in r.json().get('messages', [])]
            
            # Step 3: Write (Delete) using the same fresh session
            if ids:
                return self.delete_sms(";".join(ids))
            return 200
        except Exception:
            self.stok = None
            raise

    def get_AD(self):
        version = self.get_version()
        if not version: return ""
        is_new_gen = any(m in version for m in ["MC888", "MC889"])
        hash_func = (lambda s: hashlib.sha256(s.encode()).hexdigest().upper()) if is_new_gen else (lambda s: hashlib.md5(s.encode()).hexdigest())
        a = hash_func(version)
        rd = self.get_RD()
        return hash_func(a + rd)

    def get_RD(self):
        url = f"{self.referer}goform/goform_get_cmd_process?isTest=false&cmd=RD"
        headers = {"Referer": f"{self.referer}index.html", "Cookie": self.stok}
        try:
            r = self.session.get(url, headers=headers, timeout=self.timeout)
            return r.json().get("RD", "")
        except: return ""


if __name__ == "__main__":
    # Local debugging
    TEST_IP = "TYPE_IP_HERE" 
    TEST_USER = "TYPE_USER_HER"
    TEST_PWD = "TYPE_PASSOWRD_HERE_AND_RUN_MANUAL_IN_TERMINAL_FOR_DEBUG"

    print(f"--- Comprehensive ZTE Data Fetch ---")
    api = ZTERouterAPI(TEST_IP, TEST_USER, TEST_PWD)
    api.try_set_protocol()
    
    try:
        print("Fetching Master Blob (Router Stats)...")
        data = api.get_all_data()
        
        print("Fetching SMS Capacity Info (Stats)...")
        data.update(api.get_sms_capacity())
        
        print("Fetching and Decoding Last SMS...")
        data["last_sms"] = api.get_last_sms_content()
        
        print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")
