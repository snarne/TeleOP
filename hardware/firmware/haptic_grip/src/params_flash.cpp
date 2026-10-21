// Flash persistence through the arduino-pico EEPROM emulation (one 4 kB sector).
#ifdef ARDUINO
#include <EEPROM.h>

#include "params_store.h"

namespace hgm {

bool params_load(StoredParams* p) {
  EEPROM.begin(512);
  StoredParams tmp;
  EEPROM.get(0, tmp);
  if (tmp.magic != kParamsMagic || tmp.version != kParamsVersion || tmp.crc != params_crc(tmp)) {
    params_defaults(p);
    return false;
  }
  *p = tmp;
  return true;
}

bool params_save(StoredParams* p) {
  p->crc = params_crc(*p);
  EEPROM.put(0, *p);
  return EEPROM.commit();
}

}  // namespace hgm
#endif
