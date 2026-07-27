"""Constants for the ZTE Router 5G Monitor integration."""

DOMAIN = "zte_router_5g"

# This is the default prefix used for the Integration Title and Entity IDs
# if the user doesn't provide a custom name during setup.
DEFAULT_NAME = "ZTE 5G"
CONF_NAME = "name"

# Legacy or internal naming if needed
NAME = "ZTE Router 5G Monitor"

# Storage keys
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STOP_POLLING = "stop_polling"

# Options that may be applied without reloading the config entry.
#
# Reloading on an options change is the safe default (dev_standards Section 9):
# it guarantees the entity set and the options stay in sync. Only options that
# are read dynamically on every cycle — and that change neither the entity
# topology nor how we connect — may live-apply. Both of these qualify: the
# coordinator re-reads `stop_polling` at the top of each update, and the scan
# interval is applied straight onto `update_interval`.
#
# Anything NOT listed here reloads. That deliberately includes host, username
# and password: live-applying a connection change would leave the running API
# client pointed at the old device with the old credentials.
LIVE_OPTION_KEYS = frozenset({CONF_SCAN_INTERVAL, CONF_STOP_POLLING})
