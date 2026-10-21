# Host-native unit tests for the HGM firmware's pure modules.
#   make -C hardware/firmware/haptic_grip/test/native
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
SRC = ../../src
PROTO = ../../../common/hgm_protocol
VECTORS ?= ../../../../../tests/vectors/haptic_protocol.json

test_main: test_main.cpp $(PROTO)/protocol.cpp $(SRC)/*.cpp $(SRC)/*.h minijson.h
	$(CXX) $(CXXFLAGS) -I$(SRC) -I$(PROTO) -o $@ test_main.cpp $(PROTO)/protocol.cpp $(SRC)/control.cpp $(SRC)/params_store.cpp $(SRC)/cue.cpp -lm

run: test_main
	./test_main $(VECTORS)

.DEFAULT_GOAL := run
.PHONY: run clean
clean:
	rm -f test_main
