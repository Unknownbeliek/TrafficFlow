// Verification suite for the ES-251 error analysis and method comparison.
//
// Everything printed here is regenerated from one command (`trackflow verify`
// or menu option 2) and written to reports/*.csv, so no number in the lab
// report has to be transcribed from a screenshot.
#pragma once
#include <string>

namespace tf {
int runVerification(const std::string &outDir);
}
