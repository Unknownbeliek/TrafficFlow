# Trackflow engine build.  C++17, no external dependencies.
CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic
LDFLAGS  ?=

SRC := $(wildcard src/*.cpp)
OBJ := $(SRC:.cpp=.o)
DEP := $(OBJ:.o=.d)
BIN := trackflow_engine

.PHONY: all clean verify run asan

all: $(BIN)

$(BIN): $(OBJ)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJ) $(LDFLAGS)

# -MMD -MP so a change to a header rebuilds everything that includes it
src/%.o: src/%.cpp
	$(CXX) $(CXXFLAGS) -Isrc -MMD -MP -c -o $@ $<

-include $(DEP)

verify: $(BIN)
	./$(BIN) --verify

run: $(BIN)
	./$(BIN) --run 600

asan:
	$(CXX) -std=c++17 -g -fsanitize=address,undefined -Isrc -o /tmp/trackflow_asan src/*.cpp

clean:
	rm -f $(OBJ) $(DEP) $(BIN)
