/*******************************************************************************
 * Copyright 2017-2018 Intel Corporation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *******************************************************************************/
#include <algorithm>
#include <fstream>
#include <iostream>
#include <sstream>

#include "tensorflow/core/framework/attr_value_util.h"
#include "tensorflow/core/framework/graph.pb.h"
#include "tensorflow/core/framework/node_def_util.h"
#include "tensorflow/core/graph/graph.h"
#include "tensorflow/core/platform/default/logging.h"
#include "tensorflow/core/platform/protobuf.h"
#include "tensorflow/core/util/device_name_utils.h"

#include "ngraph_assign_clusters.h"
#include "ngraph_deassign_clusters.h"
#include "ngraph_log.h"
#include "ngraph_utils.h"

using namespace std;

namespace tensorflow {

namespace ngraph_bridge {

//
// The clustering pass of ngraph_assign_clusters.cc sometimes generates many
// small, trivial clusters. In this pass, we simply deassign (i.e., remove the
// _ngraph_cluster and _ngraph_marked_for_clustering attributes) any such
// trivial clusters. For now, "trivial" just means that there are not at least
// two non-trivial ops in the graph, where a "trivial op" means "Const" or
// "Identity".
//
// For unit testing purposes, this pass can be bypassed by setting
// NGRAPH_TF_DISABLE_DEASSIGN_CLUSTERS=1.
//

static const int MIN_NONTRIVIAL_NODES = 2;

Status DeassignClusters(Graph* graph) {
  //
  // When running unit tests, we do not want to see trivial clusters
  // deassigned. This flag (used by the Python tests) makes this possible.
  //
  if (std::getenv("NGRAPH_TF_DISABLE_DEASSIGN_CLUSTERS") != nullptr) {
    return Status::OK();
  }

  std::map<int, std::set<Node*>> cluster_map;

  for (auto node : graph->nodes()) {
    int cluster_idx;

    if (GetNodeCluster(node, &cluster_idx) != Status::OK()) {
      continue;
    }

    cluster_map[cluster_idx].insert(node);
  }

  for (auto& kv : cluster_map) {
    int cluster_idx = kv.first;
    std::set<Node*>& nodes = kv.second;

    int non_trivial_count = 0;

    for (auto node : nodes) {
      // TODO(amprocte): less hard-coding here
      if (node->type_string() != "Const" && node->type_string() != "Identity") {
        non_trivial_count++;
      }
    }

    if (non_trivial_count < MIN_NONTRIVIAL_NODES) {
      NGRAPH_VLOG(2) << "Busting cluster " << cluster_idx;
      for (auto node : nodes) {
        NGRAPH_VLOG(2) << "Busting node: " << node->name() << " ["
                       << node->type_string() << "]";

        // TODO(amprocte): move attr name to a constant
        node->ClearAttr("_ngraph_cluster");
        // TODO(amprocte): move attr name to a constant
        node->ClearAttr("_ngraph_marked_for_clustering");
      }
    }
  }

  return Status::OK();
}

}  // namespace ngraph_bridge

}  // namespace tensorflow