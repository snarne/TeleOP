# Host-native unit tests for the FGS firmware's pure modules.
#   make -C hardware/firmware/fingertip/test/native
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
SRC = ../../src
PROTO = ../../../common/hgm_protocol
VECTORS ?= ../../../../../tests/vectors/haptic_protocol.json
OBJS = $(PROTO)/protocol.cpp $(SRC)/dsp.cpp $(SRC)/ads131m02.cpp $(SRC)/fgs_params.cpp $(SRC)/engine.cpp

test_main: test_main.cpp $(OBJS) $(SRC)/*.h ../../../haptic_grip/test/native/minijson.h
	$(CXX) $(CXXFLAGS) -I$(SRC) -I$(PROTO) -I../../../haptic_grip/test/native -o $@ test_main.cpp $(OBJS) -lm

run: test_main
	./test_main $(VECTORS)

.DEFAULT_GOAL := run
.PHONY: run clean
clean:
	rm -f test_main
