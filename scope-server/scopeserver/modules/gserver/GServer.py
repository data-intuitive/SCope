from concurrent import futures
import time
import grpc
from scopeserver.modules.gserver import s_pb2
from scopeserver.modules.gserver import s_pb2_grpc

import loompy as lp
from loompy import LoomConnection
import hashlib
import os
import math
import numpy as np
import pandas as pd
import time
import json
import glob

_ONE_DAY_IN_SECONDS = 60 * 60 * 24

hexarr = np.vectorize('{:02x}'.format)


class SCope(s_pb2_grpc.MainServicer):

    def __init__(self):
        self.active_loom_connections = {}
        self.loom_dir = os.path.join("data", "my-looms")

    @staticmethod
    def get_partial_md5_hash(file_path, last_n_kb):
        with open(file_path, 'rb') as f:
            f.seek(- last_n_kb * 1024, 2)
            return hashlib.md5(f.read()).hexdigest()

    def add_loom_connection(self, partial_md5_hash, loom):
        self.active_loom_connections[partial_md5_hash] = loom

    def get_loom_filepath(self, loom_file_name):
        return os.path.join(self.loom_dir, loom_file_name)

    def load_loom_file(self, partial_md5_hash, loom_file_path):
        loom = lp.connect(loom_file_path)
        self.add_loom_connection(partial_md5_hash, loom)
        return loom

    def get_loom_connection(self, loom_file_path):
        if not os.path.exists(loom_file_path):
            raise ValueError('The file located at ' +
                             loom_file_path + ' does not exist.')
        # To check if the given file path is given specified url!
        partial_md5_hash = SCope.get_partial_md5_hash(
            loom_file_path, 10000)
        if partial_md5_hash in self.active_loom_connections:
            return self.active_loom_connections[partial_md5_hash]
        else:
            print("Debug: loading the loom file from " + loom_file_path + "...")
            return self.load_loom_file(partial_md5_hash, loom_file_path)

    def get_nb_cells(self, loom_file_path):
        loom = self.get_loom_connection(loom_file_path)
        return loom.shape[1]

    def get_gene_expression(self, loom_file_path, gene_symbol, log_transform=True, cpm_normalise=False):
        loom = self.get_loom_connection(loom_file_path)
        print("Debug: getting expression of " + gene_symbol + "...")
        print(log_transform, cpm_normalise)
        gene_expr = loom[loom.ra.Gene == gene_symbol, :][0]
        if log_transform:
            print("Debug: log-transforming gene expression...")
            gene_expr = np.log2(gene_expr + 1)
        if cpm_normalise:
            print("Debug: CPM normalising gene expression...")
            gene_expr = gene_expr / loom.ca.nUMI
            gene_expr = gene_expr
        return gene_expr

    def get_auc_values(self, loom_file_path, regulon):
        loom = self.get_loom_connection(loom_file_path)
        print("Debug: getting AUC values for {0} ...".format(regulon))
        if regulon in loom.ca.RegulonsAUC.dtype.names:
            return loom.ca.RegulonsAUC[regulon]
        return []

    def get_features(self, loom_file_path, query):
        loom = self.get_loom_connection(loom_file_path)
        # Genes
        # Filter the genes by the query

        # Allow caps innsensitive searching, minor slowdown
        start_time = time.time()
        res = []
        resF = []
        regulonList = list(loom.ra.Regulons.dtype.names)
        origSpace = list(loom.ra.Gene) + regulonList
        searchSpace = [x.casefold() for x in loom.ra.Gene] + [x.casefold() for x in regulonList]
        fType = ['gene' for x in loom.ra.Gene] + ['regulon' for x in regulonList]

        for n, x in enumerate(searchSpace):
            if query.casefold() in x:
                res.append(origSpace[n])
                resF.append(fType[n])
        for n, r in enumerate(res):
            if r.startswith(query) or query in r:
                r = res.pop(n)
                res = [r] + res
                f = resF.pop(n)
                resF = [f] + resF
        for r in res:
            if r == query:
                r = res.pop(n)
                res = [r] + res
                f = resF.pop(n)
                resF = [f] + resF

        # res = list(filter(lambda x: x.startswith(query), loom.ra.Gene))
        # res_json = json.dumps({"gene": {"name": "gene", "results": list(map(lambda x: {"title":x,"description":"","image":"", "price":""}, res))}}, ensure_ascii=False)
        # print(res_json)
        print("Debug: " + str(len(res)) + " genes matching '" + query + "'")
        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))

        return {'feature': res,
                'featureType': resF}

    def get_coordinates(self, loom_file_path, EmbeddingName='Embedding'):
        loom = self.get_loom_connection(loom_file_path)
        embedding = loom.ca[EmbeddingName]
        return {"x": embedding["_X"],
                "y": embedding["_Y"]}

    def compressHexColor(self, a):
        a = int(a, 16)
        a_hex3d = hex(a >> 20 << 8 | a >> 8 & 240 | a >> 4 & 15)
        return a_hex3d.replace("0x", "")

    def getVmax(self, vals):
        vmax = np.percentile(vals, 99)
        if vmax == 0 and max(vals) != 0:
            vmax = max(vals)
        if vmax < 10:
            vmax = max(vals)
        return vmax

    def getCellColorByFeatures(self, request, context):
        # request content
        #   - lfp   = .loom file path
        #   - e     = entries
        #   - f     = features
        #   - lte   = log transform expression
        start_time = time.time()
        loomFilePath = self.get_loom_filepath(request.loomFilePath)
        n_cells = self.get_nb_cells(loomFilePath)
        features = []
        for n, feature in enumerate(request.feature):
            if request.featureType[n] == 'gene':
                if feature != '':
                    vals = self.get_gene_expression(
                        loom_file_path=loomFilePath, gene_symbol=feature, log_transform=request.hasLogTranform, cpm_normalise=request.hasCpmTranform)
                    vmax = self.getVmax(vals)
                    vals = np.round(vals / vmax) * 255
                    features.append([x if x <= 255 else 255 for x in vals])
                else:
                    features.append(np.zeros(n_cells))
            elif request.featureType[n] == 'regulon':
                if feature != '':
                    vals = self.get_auc_values(loom_file_path=loomFilePath, regulon=feature)
                    vmax = self.getVmax(vals)
                    if request.threshold > 0.0:
                        if request.scaleThresholded:
                            vals = ([auc if auc >= request.threshold else 0 for auc in vals])
                            vals = np.round(vals / vmax) * 255
                            features.append([x if x <= 255 else 255 for x in vals])
                        else:
                            features.append([255 if auc >= request.threshold else 0 for auc in vals])
                    else:
                        features.append([x if x <= 255 else 255 for x in vals])
                else:
                    features.append(np.zeros(n_cells))

        if len(features) > 0:
            hex_vec = ["%02x%02x%02x" % (int(r), int(g), int(b)) for r, g, b in zip(features[0], features[1], features[2])]
        else:
            hex_vec = []

        print("Debug: %s seconds elapsed ---" % (time.time() - start_time))
        return s_pb2.CellColorByFeaturesReply(color=hex_vec)

    def getCellAUCValuesByFeatures(self, request, context):
        loomFilePath = self.get_loom_filepath(request.loomFilePath)
        return s_pb2.CellAUCValuesByFeaturesReply(value=self.get_auc_values(loom_file_path=loomFilePath, regulon=request.feature[0]))

    def getFeatures(self, request, context):
        f = self.get_features(self.get_loom_filepath(request.loomFilePath), request.query)
        return s_pb2.FeatureReply(feature=f['feature'], featureType=f['featureType'])

    def getCoordinates(self, request, context):
        # request content
        c = self.get_coordinates(self.get_loom_filepath(request.loomFilePath))
        return s_pb2.CoordinatesReply(x=c["x"], y=c["y"])

    def getMyLooms(self, request, context):
        my_looms = []
        for f in os.listdir(self.loom_dir):
            if f.endswith('.loom'):
                my_looms.append(s_pb2.MyLoom(loomFilePath=f,
                                             cellMetaData=s_pb2.CellMetaData(annotations=[], clusterings=[]),
                                             regulonMetaData=s_pb2.RegulonMetaData(regulons=[])))
        return s_pb2.MyLoomsReply(myLooms=my_looms)


def serve(run_event):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    s_pb2_grpc.add_MainServicer_to_server(SCope(), server)
    server.add_insecure_port('[::]:50052')
    print('Starting GServer on port 50052...')

    server.start()

    while run_event.is_set():
        time.sleep(0.1)

    server.stop(0)


if __name__ == '__main__':
    serve()
