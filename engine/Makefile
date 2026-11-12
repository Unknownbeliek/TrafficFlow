# Trackflow engine — plain C++17, no external dependencies.
# `make` builds ./trackflow, `make verify` regenerates the ES-251 tables.

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unused-parameter
SRC      := $(wildcard src/*.cpp)
OBJ      := $(SRC:src/%.cpp=build/%.o)
DEP      := $(OBJ:.o=.d)

trackflow: $(OBJ)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJ)

build/%.o: src/%.cpp
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -MMD -MP -c $< -o $@

verify: trackflow
	./trackflow verify reports

clean:
	rm -rf build trackflow

.PHONY: verify clean

-include $(DEP)
