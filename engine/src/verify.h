#pragma once

#include <string>

namespace tj {
namespace verify {
// Regenerate verification/*.csv and print the summary table.
int run(const std::string &network_path);
}  // namespace verify
}  // namespace tj
