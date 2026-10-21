// Small float biquad (Direct Form I) with RBJ-cookbook designs. Pure C++, host-testable.
#pragma once

#include <math.h>

namespace hgm {

struct Biquad {
  float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
  float x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  bool primed = false;

  // Notch at f0 (Hz) with quality Q, sampled at fs (Hz). Unity gain at DC.
  static Biquad notch(float f0, float q, float fs) {
    Biquad b;
    const float w = 2.f * 3.14159265f * f0 / fs, c = cosf(w), al = sinf(w) / (2.f * q), a0 = 1.f + al;
    b.b0 = 1.f / a0; b.b1 = -2.f * c / a0; b.b2 = 1.f / a0; b.a1 = -2.f * c / a0; b.a2 = (1.f - al) / a0;
    return b;
  }
  float step(float x) {
    if (!primed) {  // start at steady state so the first samples don't ring
      x1 = x2 = x;
      y1 = y2 = x * (b0 + b1 + b2) / (1.f + a1 + a2);
      primed = true;
    }
    const float y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
    x2 = x1; x1 = x; y2 = y1; y1 = y;
    return y;
  }
};

}  // namespace hgm
