import numpy as np
import re
import itertools
import time
import zlib
import sys

from scopeserver.dataserver.modules.gserver import s_pb2
from scopeserver.utils import Constant

class CellColorByFeatures():

    def __init__(self, loom):
        self.loom = loom
        self.meta_data = loom.get_meta_data()
        self.n_cells = loom.get_nb_cells()
        self.features = []
        self.hex_vec = []
        self.v_max = np.zeros(3)
        self.max_v_max = np.zeros(3)
        self.cell_indices = list(range(self.n_cells))
        self.reply = None
    
    @staticmethod # TO GET FROM GServer SCOPE
    def get_vmax(vals):
        maxVmax = max(vals)
        vmax = np.percentile(vals, 99)
        if vmax == 0 and max(vals) != 0:
            vmax = max(vals)
        if vmax == 0:
            vmax = 0.01
        return vmax, maxVmax

    @staticmethod
    def compress_str_array(str_arr):
        print("Compressing... ")
        str_array_size = sys.getsizeof(str_arr)
        str_array_joint = bytes(''.join(str_arr), 'utf-8')
        str_array_joint_compressed = zlib.compress(str_array_joint, 1)
        str_array_joint_compressed_size = sys.getsizeof(str_array_joint_compressed)
        savings_percent = 1-str_array_joint_compressed_size/str_array_size
        print("Saving "+"{:.2%} of space".format(savings_percent))
        return str_array_joint_compressed
    
    def get_features(self):
        return self.features

    def get_hex_vec(self):
        for _ in itertools.repeat(None, 3-len(self.features)):
            self.addEmptyFeature()
        if len(self.features) > 0 and len(self.hex_vec) == 0:
            self.hex_vec = ["XXXXXX" if r == g == b == 0
                       else "{0:02x}{1:02x}{2:02x}".format(int(r), int(g), int(b))
                       for r, g, b in zip(self.features[0], self.features[1], self.features[2])]
        return self.hex_vec
    
    def get_compressed_hex_vec(self):
        comp_start_time = time.time()
        hex_vec_compressed = CellColorByFeatures.compress_str_array(str_arr=self.get_hex_vec())
        print("Debug: %s seconds elapsed (compression) ---" % (time.time() - comp_start_time))
        return hex_vec_compressed

    def get_v_max(self):
        return self.v_max

    def get_max_v_max(self):
        return self.max_v_max

    def get_cell_indices(self):
        return self.cell_indices
    
    def setGeneFeature(self, request, feature, n):
        if feature != '':
            vals, self.cellIndices = self.loom.get_gene_expression(
                gene_symbol=feature,
                log_transform=request.hasLogTransform,
                cpm_normalise=request.hasCpmTransform,
                annotation=request.annotation,
                logic=request.logic)
            if request.vmax[n] != 0.0:
                self.v_max[n] = request.vmax[n]
            else:
                self.v_max[n], self.max_v_max[n] = CellColorByFeatures.get_vmax(vals)
            # vals = np.round((vals / vmax[n]) * 225)
            vals = vals / self.v_max[n]
            vals = (((Constant._UPPER_LIMIT_RGB - Constant._LOWER_LIMIT_RGB) * (vals - min(vals))) / (1 - min(vals))) + Constant._LOWER_LIMIT_RGB
            self.features.append([x if x <= Constant._UPPER_LIMIT_RGB else Constant._UPPER_LIMIT_RGB for x in vals])
        else:
            self.features.append(np.zeros(self.n_cells))

    def setRegulonFeature(self, request, feature, n):
        if feature != '':
            vals, self.cellIndices = self.loom.get_auc_values(regulon=feature,
                                                    annotation=request.annotation,
                                                    logic=request.logic)
            if request.vmax[n] != 0.0:
                self.v_max[n] = request.vmax[n]
            else:
                self.v_max[n], self.max_v_max[n] = CellColorByFeatures.get_vmax(vals)
            if request.scaleThresholded:
                vals = ([auc if auc >= request.threshold[n] else 0 for auc in vals])
                # vals = np.round((vals / vmax[n]) * 225)
                vals = vals / self.v_max[n]
                vals = (((Constant._UPPER_LIMIT_RGB - Constant._LOWER_LIMIT_RGB) * (vals - min(vals))) / (1 - min(vals))) + Constant._LOWER_LIMIT_RGB
                self.features.append([x if x <= Constant._UPPER_LIMIT_RGB else Constant._UPPER_LIMIT_RGB for x in vals])
            else:
                self.features.append([Constant._UPPER_LIMIT_RGB if auc >= request.threshold[n] else 0 for auc in vals])
        else:
            self.features.append(np.zeros(self.n_cells))
    
    def setAnnotationFeature(self, feature):
        md_annotation_values = self.loom.get_meta_data_annotation_by_name(name=feature)["values"]
        ca_annotation = self.loom.get_ca_attr_by_name(name=feature)
        ca_annotation_as_int = list(map(lambda x: md_annotation_values.index(str(x)), ca_annotation))
        num_annotations = max(ca_annotation_as_int)
        if num_annotations <= len(Constant.BIG_COLOR_LIST):
            self.hex_vec = list(map(lambda x: Constant.BIG_COLOR_LIST[x], ca_annotation_as_int))
        else:
            raise ValueError("The annotation {0} has too many unique values.".format(feature))
        # Set the reply
        reply = s_pb2.CellColorByFeaturesReply(color=self.hex_vec,
                                               vmax=self.v_max,
                                               legend=s_pb2.ColorLegend(values=md_annotation_values, colors=Constant.BIG_COLOR_LIST[:len(md_annotation_values)]))
        self.setReply(reply=reply)
    
    def setMetricFeature(self, request, feature, n):
        if feature != '':
            vals, self.cell_indices = self.loom.get_metric(
                metric_name=feature,
                log_transform=request.hasLogTransform,
                cpm_normalise=request.hasCpmTransform,
                annotation=request.annotation,
                logic=request.logic)
            if request.vmax[n] != 0.0:
                self.v_max[n] = request.vmax[n]
            else:
                self.v_max[n], self.max_v_max[n] = CellColorByFeatures.get_vmax(vals)
            # vals = np.round((vals / vmax[n]) * 225)
            vals = vals / self.v_max[n]
            vals = (((Constant._UPPER_LIMIT_RGB - Constant._LOWER_LIMIT_RGB) * (vals - min(vals))) / (1 - min(vals))) + Constant._LOWER_LIMIT_RGB
            self.features.append([x if x <= Constant._UPPER_LIMIT_RGB else Constant._UPPER_LIMIT_RGB for x in vals])
        else:
            self.features.append(np.zeros(self.n_cells))
    
    def setClusteringFeature(self, request, feature, n):
        clusteringID = None
        clusterID = None
        print("Getting clustering: {0}".format(request.feature[n]))
        for clustering in self.meta_data['clusterings']:
            if clustering['name'] == re.sub('^Clustering: ', '', request.featureType[n]):
                clusteringID = str(clustering['id'])
                if request.feature[n] == 'All Clusters':
                    numClusters = max(self.loom.get_clustering_by_id(clusteringID))
                    if numClusters <= 245:
                        for i in self.loom.get_clustering_by_id(clusteringID):
                            self.hex_vec.append(Constant.BIG_COLOR_LIST[i])
                    else:
                        interval = int(16581375 / numClusters)
                        hex_vec = [hex(I)[2:].zfill(6) for I in range(0, numClusters, interval)]
                    if len(request.annotation) > 0:
                        cellIndices = self.loom.get_anno_cells(annotations=request.annotation, logic=request.logic)
                        hex_vec = np.array(hex_vec)[cellIndices]
                    # Set the reply and break the for loop
                    reply = s_pb2.CellColorByFeaturesReply(color=self.hex_vec, vmax=self.v_max)
                    self.setReply(reply=reply)
                    break
                else:
                    for cluster in clustering['clusters']:
                        if request.feature[n] == cluster['description']:
                            clusterID = int(cluster['id'])

        if clusteringID is None and clusterID is None and len(request.feature[n]) > 0:
            error_message = "The cluster '{0}' does not exist in the current active .loom. Clear the query to continue with SCope.".format(request.feature[n])
            self.setReply(s_pb2.CellColorByFeaturesReply(error=s_pb2.ErrorReply(type="Value Error", message=error_message)))

        if clusteringID is not None and clusterID is not None:
            clusterIndices = self.loom.get_clustering_by_id(clusteringID) == clusterID
            clusterCol = np.array([Constant._UPPER_LIMIT_RGB if x else 0 for x in clusterIndices])
            if len(request.annotation) > 0:
                cellIndices = self.loom.get_anno_cells(annotations=request.annotation, logic=request.logic)
                clusterCol = clusterCol[cellIndices]
            self.features.append(clusterCol)

    def addEmptyFeature(self):
        self.features.append([Constant._LOWER_LIMIT_RGB for n in range(self.n_cells)])

    def hasReply(self):
        return self.reply != None

    def setReply(self, reply):
        self.reply = reply
    
    def getReply(self):
        return self.reply


