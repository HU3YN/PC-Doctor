# Host tests for the firmware code that has no Arduino dependency.
#
#   make          build and run the tests
#   make tool     build pcd_tool (encode/decode packets from the command line)
#   make clean    delete the build folder
#
# Only a C and a C++ compiler are needed. The library is compiled as C, the
# same way PlatformIO compiles it for the ESP32, and the tests as C++.

CC ?= cc
CXX ?= c++
CFLAGS ?= -std=c99 -O1 -g -Wall -Wextra -Werror -pedantic
CXXFLAGS ?= -std=c++11 -O1 -g -Wall -Wextra -Werror

LIB_DIR := ../lib/pcd_protocol/src
BUILD := build

LIB_SRCS := $(LIB_DIR)/pcd_protocol.c $(LIB_DIR)/pcd_sht31.c
LIB_OBJS := $(BUILD)/pcd_protocol.o $(BUILD)/pcd_sht31.o
HEADERS := $(LIB_DIR)/pcd_protocol.h $(LIB_DIR)/pcd_sht31.h mini_test.h

.PHONY: all test tool clean

all: test

test: $(BUILD)/test_protocol
	./$(BUILD)/test_protocol

tool: $(BUILD)/pcd_tool

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.o: $(LIB_DIR)/%.c $(HEADERS) | $(BUILD)
	$(CC) $(CFLAGS) -I$(LIB_DIR) -c $< -o $@

$(BUILD)/test_protocol: test_protocol.cpp $(LIB_OBJS) $(HEADERS) | $(BUILD)
	$(CXX) $(CXXFLAGS) -I$(LIB_DIR) test_protocol.cpp $(LIB_OBJS) -o $@

$(BUILD)/pcd_tool: pcd_tool.cpp $(LIB_OBJS) $(HEADERS) | $(BUILD)
	$(CXX) $(CXXFLAGS) -I$(LIB_DIR) pcd_tool.cpp $(LIB_OBJS) -o $@

clean:
	rm -rf $(BUILD)
