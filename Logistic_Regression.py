# 修改至zgl路径下！！！
# environment:  Remote Python 3.9.16 (/home/user/anaconda3/envs/envzgl/bin/python3.9) (3) /home/user/anaconda3/envs/envzgl/bin/python3.9
import numpy as np
import math
import os
# import matplotlib.pyplot as plt
from scipy.sparse import csr_matrix, lil_matrix, coo_matrix
#########################
####succeed###########3##
import sys
import time
from multiprocessing.pool import Pool

dir_path = os.path.dirname(os.path.realpath(__file__))
abs_pardir = os.path.join(dir_path, os.pardir)
abs_parpardir = os.path.join(abs_pardir, os.pardir)
sys.path.append(abs_parpardir)

from data_processing.dataset_select import dataset_selector
# from data_processing.sketch_squeece import *
from data_processing.kernel_approximate_method import dataSketch_generator_RBFandPolyKernel

PATH_DATA = '/home/user/zbz/SSHE/data/'
PATH_FILE = '/home/user/zbz/SSHE/logistic_regression/nompc/result/'


class LogisticRegression:
    """
    logistic回归
    """

    def __init__(self, weight_vector, batch_size, max_iter, alpha,
                 eps, ratio=None, penalty=None, lambda_para=1, data_tag=None, c=1, ovr=None, Epoch_list_max=None):
        """
        构造函数:初始化
        """
        self.model_weights = weight_vector
        self.batch_size = batch_size  # 设置的batch大小
        self.batch_num = []  # 存储每个batch的大小
        self.n_iteration = 0
        self.max_iter = max_iter
        self.alpha = alpha
        self.pre_loss = 0
        self.eps = eps  # 训练的误差下限
        self.ratio = ratio  # 数据集划分比例
        self.penalty = penalty  # 正则化策略
        self.lambda_para = lambda_para  # 正则化系数
        self.data_tag = data_tag  # 输入数据的格式 (目前需要支持两种格式: sparse和dense)
        self.c = c
        self.ovr = ovr
        # self.modelWeight
        # self.OVRModel_Agg
        EPOCH_list = [i for i in range(1, Epoch_list_max+1)]    # Epoch_list_max代表了需要记录准确率的轮次，从第一轮开始
        self.EPOCH_list = EPOCH_list
        assert(self.EPOCH_list[-1] <= self.max_iter)

        if self.ovr == "bin": self.modelWeight = []
        elif self.ovr == "ovr": self.OVRModel_Agg = dict() # 用于存储每个标签对应的二分类模型, 其中每一个标签下的模型也是一个字典, 字典内容是不同epoch下的模型参数和时间


    def _cal_z(self, weights, features, party=None):
        # print("cal_z party: ", party)
        # print(features.shape, weights.shape)
        if party == "A":
            if self.data_tag == 'sparse':
                self.wx_self_A = features.dot(weights.T)
            else:
                self.wx_self_A = np.dot(features, weights.T)
        elif party == "B":
            if self.data_tag == 'sparse':
                self.wx_self_B = features.dot(weights.T)
            else:
                self.wx_self_B = np.dot(features, weights.T)

        else:
            if self.data_tag == 'sparse':
                self.wx_self = features.dot(weights.T)  # np.dot(features, weights.T)
            elif self.data_tag == None:
                self.wx_self = np.dot(features, weights.T)
        # return self.wx_self

    # def _compute_sigmoid(self, z):
    #     return 1 / (1 + np.exp(-z))
    #
    # def _compute_sigmoid_approx(self, arr):
    #     mask = np.logical_and(arr > -0.5, arr < 0.5)
    #     arr[mask] = arr[mask]
    #     arr[~mask] = 0
    #     return arr
    #
    # def _compute_sigmoid3(self, z):
    #     # return 1 / (1 + np.exp(-z))
    #     # print(type(z))
    #     # if self.data_tag == None:
    #     return -0.004 * z*z*z + 0.197*z + 0.5

    def _compute_sigmoid(self, z):
        # linear approximation 一次函数 / cube approximation 三次函数 / segmentation approximation 分段函数 / original sigmoid 原激活函数
        if sigmoid_func == "linear":
            yhat = z * 0.25 + 0.5
        elif sigmoid_func == "cube":
            yhat = -0.004 * z*z*z + 0.197*z + 0.5
        elif sigmoid_func == "segmentation":
            mask = np.logical_and(z > -0.5, z < 0.5)
            z[mask] = z[mask]
            z[~mask] = 0
            yhat = z
        elif sigmoid_func == "origin":
            yhat = 1 / (1 + np.exp(-z))
        else:
            print("No sigmoid_func named {}, please correct it!".format(sigmoid_func))
            return "ERROR!"
        return yhat

    def _compute_sigmoid_dual_distributed(self, z):
        # return 1 / (1 + np.exp(-z))
        # print(type(z))
        # if self.data_tag == None:
        return z * 0.25

    def _compute_loss_cross_entropy(self, weights, label, batch_idx):
        """
            Use Taylor series expand log loss:
            Loss = - y * log(h(x)) - (1-y) * log(1 - h(x)) where h(x) = 1/(1+exp(-wx))
            Then loss' = - (1/N)*∑(log(1/2) - 1/2*wx + ywx -1/8(wx)^2)
        """
        # print("type label: ", type(label), type(self.wx_self), label.shape, self.wx_self.shape)
        half_wx = -0.5 * self.wx_self
        ywx = self.wx_self * label
        # ywx = np.multiply(self.wx_self, label)

        wx_square = self.wx_self * self.wx_self * -0.125  # wx_square = np.dot(self.wx_self.T, self.wx_self) * -0.125 # 这里后续要修改，两方平方，有交叉项
        # wx_square = np.multiply(self.wx_self, self.wx_self) * -0.125
        batch_num = self.batch_num[batch_idx]

        loss = np.sum((half_wx + ywx + wx_square) * (-1 / batch_num) - np.log(0.5))
        # loss = np.sum( (half_wx + ywx + wx_square) * (-1 / batch_num) )
        return loss

    def distributed_compute_loss_cross_entropy(self, label, batch_num):
        """
            Use Taylor series expand log loss:
            Loss = - y * log(h(x)) - (1-y) * log(1 - h(x)) where h(x) = 1/(1+exp(-wx))
            Then loss' = - (1/N)*∑(log(1/2) - 1/2*wx + ywx -1/8(wx)^2)
        """
        self.encrypted_wx = self.wx_self_A + self.wx_self_B
        half_wx = -0.5 * self.encrypted_wx
        ywx = self.encrypted_wx * label

        wx_square = (
                                2 * self.wx_self_A * self.wx_self_B + self.wx_self_A * self.wx_self_A + self.wx_self_B * self.wx_self_B) * -0.125  # wx_square = np.dot(self.wx_self.T, self.wx_self) * -0.125 # 这里后续要修改，两方平方，有交叉项
        # wx_square2 = self.encrypted_wx * self.encrypted_wx * -0.125
        # assert all(wx_square == wx_square2)  # 数组比较的返回值为: 类似[True False False]

        loss = np.sum((half_wx + ywx + wx_square) * (-1 / batch_num) - np.log(0.5))
        # loss = np.sum( (half_wx + ywx + wx_square) * (-1 / batch_num) )
        return loss

    # def _compute_loss(self, y, label, batch_idx):
    #     batch_num = self.batch_num[batch_idx]
    #     loss = -1 * label * np.log(y) - (1 - label) * np.log(1 - y)
    #     return np.sum(loss)

    def forward(self, weights, features):  # , batch_weight):
        # print("weights: ", type(weights))
        # print("features: ", type(features))
        self._cal_z(weights, features, party=None)
        # sigmoid
        # print("self.wx_self: ", type(self.wx_self))
        # print(self.wx_self)
        sigmoid_z = self._compute_sigmoid(self.wx_self)
        return sigmoid_z

    def distributed_forward(self, weights, features, party=None):  # , batch_weight):
        # print("party: ", party)
        self._cal_z(weights, features, party)
        # # sigmoid
        # if party == "A":
        #     sigmoid_z = self._compute_sigmoid(self.wx_self_A)
        # elif party == "B":
        #     # sigmoid_z = self._compute_sigmoid(self.wx_self_B)
        #     # 注意这里考虑到分布式的计算问题, 少加了一个0.5, 这样后面y1+y2-label计算loss的时候才是正确的error值
        #     sigmoid_z = self._compute_sigmoid_dual_distributed(self.wx_self_B)

        # return sigmoid_z

    def backward(self, error, features, batch_idx):
        # print("batch_idx: ",batch_idx)
        batch_num = self.batch_num[batch_idx]
        # print("error, feature shape: ", error.T.shape, features.shape)
        # print("error, feature type: ", type(error.T), type(features))
        if self.data_tag == 'sparse':
            gradient = features.T.dot(error).T / batch_num  # 稀疏矩阵
        elif self.data_tag == None:
            gradient = np.dot(error.T, features) / batch_num  # 非稀疏矩阵
        # print("gradient shape: ", gradient.shape)
        return gradient

    def distributed_backward(self, error, features, batch_num):
        # print("batch_idx: ",batch_idx)
        # batch_num = self.batch_num[batch_idx]
        if self.data_tag == 'sparse':
            gradient = features.T.dot(error).T / batch_num  # 稀疏矩阵
        elif self.data_tag == None:
            gradient = np.dot(error.T, features) / batch_num  # 非稀疏矩阵
        return gradient

    def check_converge_by_loss(self, loss):
        converge_flag = False
        if self.pre_loss is None:
            pass
        elif abs(self.pre_loss - loss) < self.eps:
            converge_flag = True
        self.pre_loss = loss
        return converge_flag

    def shuffle_data(self, Xdatalist, Ydatalist):
        # X_batch_list
        # np.random.shuffle(X_data)
        zip_list = list(zip(Xdatalist, Ydatalist))  # 将a,b整体作为一个zip,每个元素一一对应后打乱
        np.random.shuffle(zip_list)  # 打乱c
        Xdatalist[:], Ydatalist[:] = zip(*zip_list)
        return Xdatalist, Ydatalist

    def shuffle_distributed_data(self, XdatalistA, XdatalistB, Ydatalist, batch_num):
        # X_batch_list
        # np.random.shuffle(X_data)
        zip_list = list(zip(XdatalistA, XdatalistB, Ydatalist, batch_num))  # 将a,b整体作为一个zip,每个元素一一对应后打乱
        np.random.shuffle(zip_list)  # 打乱c
        XdatalistA[:], XdatalistB[:], Ydatalist[:], batch_num[:] = zip(*zip_list)
        return XdatalistA, XdatalistB, Ydatalist, batch_num

    def decay_learning_rate(self, alpha):
        self.decay = 1
        if self.n_iteration % 10 == 0:
            # if True: #self.decay_sqrt:
            # self.alpha = self.alpha / np.sqrt(1 + self.decay * self.n_iteration)
            alpha = alpha * 0.95
        # else:
        #     self.alpha = self.alpha / (1 + self.decay * self.n_iteration)]
        else:
            alpha = alpha
        return alpha

    # 理想集中 和 将一部分数据划分为两部分的纵向分布式
    def fit_model(self, X_train, Y_train, instances_count):
        # mini-batch 数据集处理
        print("ratio: ", self.ratio)
        if self.ratio is None:
            X_batch_list, y_batch_list = self._generate_batch_data(X_train, Y_train, self.batch_size)
        elif self.data_tag == None:
            X_batch_listA, X_batch_listB, y_batch_list = self._distributed_generate_batch_data(X_train, Y_train,
                                                                                               self.batch_size,
                                                                                               self.ratio)
            self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice])  # 权重向量是一个列向量，需要横向划分
        elif self.data_tag == 'sparse':
            print('sprase data batch generating...')
            X_batch_listA, X_batch_listB, y_batch_list = self._distributed_generate_sparse_batch_data(X_train, Y_train,
                                                                                                      self.batch_size,
                                                                                                      self.ratio)
            self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice])  # 权重向量是一个列向量，需要横向划分
            print('Generation done.')
        else:
            raise Exception(
                "[fit model] No proper entry for batch data generation. Check the data_tag or the fit function.")

        self.n_iteration = 0
        self.loss_history = []
        test = 0

        while self.n_iteration < self.max_iter:
            loss_list = []
            batch_labels = None
            if self.ratio == None:

                for batch_idx, batch_data in enumerate(X_batch_list):
                    batch_labels = y_batch_list[batch_idx].reshape(-1, 1)  # 转换成1列的列向量
                    # print("batch data: ", type(batch_data))

                    ## forward and backward
                    y = self.forward(self.model_weights, batch_data)
                    error = y - batch_labels  # 注意这里谁减谁，和后面更新梯度是加还是减有关
                    gradient = self.backward(error=error, features=batch_data, batch_idx=batch_idx)
                    ## compute loss
                    batch_loss = self._compute_loss_cross_entropy(weights=self.model_weights, label=batch_labels,
                                                                  batch_idx=batch_idx)
                    # batch_loss = self._compute_loss(y, batch_labels, batch_idx)
                    loss_list.append(batch_loss)
                    # print(error)
                    # print(gradient.T)
                    # print(batch_loss)
                    # return 0

                    ## update model
                    if self.penalty == 'l2':
                        batch_num = self.batch_num[batch_idx]
                        self.model_weights = self.model_weights - self.alpha * gradient - self.lambda_para * self.alpha * self.model_weights / batch_num
                    elif self.penalty == 'l1':
                        batch_num = self.batch_num[batch_idx]
                        self.model_weights = self.model_weights - self.alpha * gradient - self.lambda_para * self.alpha * np.sign(
                            self.model_weights) / batch_num
                    else:
                        # print("shape: ", self.model_weights.shape, gradient.shape)
                        self.model_weights = self.model_weights - self.alpha * gradient  # 30*1
                    # self.model_weights = self.model_weights - self.alpha * gradient     # 30*1
                # 打乱数据集的batch
                X_batch_list, y_batch_list = self.shuffle_data(X_batch_list, y_batch_list)

            # distributed
            else:
                # if self.n_iteration == 0:
                #     self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice]) # 权重向量是一个列向量，需要横向划分
                # print("weightA, weightB: ", self.weightA.shape, self.weightB.shape)
                for batch_dataA, batch_dataB, batch_labels, batch_num in zip(X_batch_listA, X_batch_listB, y_batch_list,
                                                                             self.batch_num):
                    batch_labels = batch_labels.reshape(-1, 1)

                    ## forward and backward
                    y1 = self.distributed_forward(self.weightA, batch_dataA, party="A")
                    y2 = self.distributed_forward(self.weightB, batch_dataB, party="B")
                    error = (y1 + y2) - batch_labels  # 注意这里谁减谁，和后面更新梯度是加还是减有关
                    # print("error: ", error)
                    self.gradient1 = self.distributed_backward(error=error, features=batch_dataA, batch_num=batch_num)
                    self.gradient2 = self.distributed_backward(error=error, features=batch_dataB, batch_num=batch_num)

                    ## compute loss
                    batch_loss = self.distributed_compute_loss_cross_entropy(label=batch_labels, batch_num=batch_num)
                    loss_list.append(batch_loss)

                    # print(error)
                    # print(self.gradient1.T, self.gradient2.T)
                    # print(batch_loss)
                    # return 0

                    ## update model
                    # self.model_weights = self.model_weights - self.alpha * gradient     # 30*1
                    self.weightA = self.weightA - self.alpha * self.gradient1
                    self.weightB = self.weightB - self.alpha * self.gradient2

                # 打乱数据集的batch
                X_batch_listA, X_batch_listB, y_batch_list = self.shuffle_distributed_data(X_batch_listA,
                                                                                           X_batch_listB, y_batch_list)
                # print("weightA, B: ", self.weightA.shape, self.weightB.shape, self.weightA[0][0], self.weightB[0][0])
            # print("gradientA, B: ", self.gradient1.shape, self.gradient1.shape, self.gradient1[0][0], self.gradient2[0][0])
            # print("weightA, B: ", self.weightA.shape, self.weightB.shape, self.weightA[0][0], self.weightB[0][0])
            ## 计算 sum loss
            loss = np.sum(loss_list) / instances_count
            print("\rIteration {}, batch sum loss: {}".format(self.n_iteration, loss))
            self.loss_history.append(loss)

            ## 判断是否停止
            self.is_converged = self.check_converge_by_loss(loss)
            if self.is_converged:
                # self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice]) # 权重向量是一个列向量，需要横向划分
                if self.ratio is not None:
                    self.model_weights = np.hstack((self.weightA, self.weightB))
                    print("self.model_weights: ", self.model_weights)
                break

            self.n_iteration += 1

    def fit_model_distributed_input(self, X_trainA, X_trainB, Y_train, instances_count, indice_littleside):
        # indice_littleside 用于划分权重, 得到特征数值较小的那一部分的权重-或者左侧 默认X1一侧
        # mini-batch 数据集处理
        # print("ratio: ", self.ratio)
        # 纵向划分数据集，位于label一侧的特征数量
        self.indice = indice_littleside  # math.floor(self.ratio * ( X_trainA.shape[1]+X_trainB.shape[1] ) )
        # if self.ratio is None:
        #     X_batch_list, y_batch_list = self._generate_batch_data(X_train, Y_train, self.batch_size)
        if self.data_tag == None:
            X_batch_listA, X_batch_listB, y_batch_list = self._generate_batch_data_for_distributed_parts(X_trainA,
                                                                                                         X_trainB,
                                                                                                         Y_train,
                                                                                                         self.batch_size)
            self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice])  # 权重向量是一个列向量，需要横向划分
            print(self.weightA.shape, self.weightB.shape)
        elif self.data_tag == 'sparse':
            # print('sprase data batch generating...')
            X_batch_listA, X_batch_listB, y_batch_list = self._generate_Sparse_batch_data_for_distributed_parts(
                X_trainA, X_trainB,
                Y_train, self.batch_size)
            self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice])  # 权重向量是一个列向量，需要横向划分
            # print('Generation done.')
        else:
            raise Exception(
                "[fit model] No proper entry for batch data generation. Check the data_tag or the fit function.")

        self.n_iteration = 1
        self.loss_history = []
        test = 0
        alpha = self.alpha

        while self.n_iteration <= self.max_iter:
            loss_list = []
            batch_labels = None
            # distributed
            for batch_dataA, batch_dataB, batch_labels, batch_num in zip(X_batch_listA, X_batch_listB, y_batch_list,
                                                                         self.batch_num):
                batch_labels = batch_labels.reshape(-1, 1)

                ## forward and backward
                # y1 = self.distributed_forward(self.weightA, batch_dataA, party = "A")
                # y2 = self.distributed_forward(self.weightB, batch_dataB, party = "B")
                self.distributed_forward(self.weightA, batch_dataA, party="A")
                self.distributed_forward(self.weightB, batch_dataB, party="B")

                # y = self.sigmoid(self.wx_self_A+self.wx_self_B)
                # y = self.sigmoid_func(self.wx_self_A+self.wx_self_B)
                y = self._compute_sigmoid(self.wx_self_A + self.wx_self_B)

                # error = (y1 + y2) - batch_labels # 注意这里谁减谁，和后面更新梯度是加还是减有关
                error = y - batch_labels  # 注意这里谁减谁，和后面更新梯度是加还是减有关
                # print("error: ", error)
                self.gradient1 = self.distributed_backward(error=error, features=batch_dataA, batch_num=batch_num)
                self.gradient2 = self.distributed_backward(error=error, features=batch_dataB, batch_num=batch_num)

                ## compute loss
                batch_loss = self.distributed_compute_loss_cross_entropy(label=batch_labels, batch_num=batch_num)
                loss_list.append(batch_loss)

                # print(error)
                # print(self.gradient1.T, self.gradient2.T)
                # print(batch_loss)
                # return 0

                ## update model

                # self.model_weights = self.model_weights - self.alpha * gradient     # 30*1
                if self.n_iteration > 1: alpha = self.decay_learning_rate(alpha)
                # self.weightA = self.weightA - self.c * self.alpha * self.gradient1 - self.lambda_para * self.alpha * self.weightA / batch_num
                # self.weightB = self.weightB - self.c * self.alpha * self.gradient2 - self.lambda_para * self.alpha * self.weightB / batch_num
                self.weightA = self.weightA - self.c * alpha * self.gradient1 - self.lambda_para * alpha * self.weightA / batch_num
                self.weightB = self.weightB - self.c * alpha * self.gradient2 - self.lambda_para * alpha * self.weightB / batch_num

                # self.weightA = self.weightA - self.c * self.alpha * self.gradient1 - self.lambda_para * self.alpha * self.weightA
                # self.weightB = self.weightB - self.c * self.alpha * self.gradient2 - self.lambda_para * self.alpha * self.weightB

                # self.weightA = self.weightA - self.c * self.alpha * self.gradient1
                # self.weightB = self.weightB - self.c * self.alpha * self.gradient2

            # 打乱数据集的batch
            # X_batch_listA, X_batch_listB, y_batch_list, self.batch_num = self.shuffle_distributed_data(X_batch_listA,
            #                     X_batch_listB, y_batch_list, self.batch_num)
            # print("weightA, B: ", self.weightA.shape, self.weightB.shape, self.weightA[0][0], self.weightB[0][0])
            # print("gradientA, B: ", self.gradient1.shape, self.gradient1.shape, self.gradient1[0][0], self.gradient2[0][0])
            # print("weightA, B: ", self.weightA.shape, self.weightB.shape, self.weightA[0][0], self.weightB[0][0])

            ## 计算 sum loss
            loss = np.sum(loss_list) / instances_count
            print("\rIteration {}, batch sum loss: {}".format(self.n_iteration, loss), end='')
            self.loss_history.append(loss)

            # #######################################################################################################################################################
            # """
            # intermediate result saving
            # """
            # if self.ovr == "bin" and self.n_iteration in self.EPOCH_list:
            #     ## Time
            #     time_end_training = time.time()
            #     epoch_Online_Calculate_timeAccount = time_end_training - time_start_training_epoch # 计算时间
            #     epoch_Online_Communicate_timeAccount = self.online_comm_time_account  # 通信时间
            #     # offline time 不同epoch应该是相同的
            #     epoch_Online_timeAccounting = epoch_Online_Calculate_timeAccount + epoch_Online_Communicate_timeAccount
            #
            #     ## save Model and Time
            #     self.modelWeight_and_Time_List.update({ str(self.n_iteration): [self.weightA + self.weightB, epoch_Online_timeAccounting, self.online_comm_time_account] })
            #
            # elif self.ovr == "ovr" and self.n_iteration in self.EPOCH_list:
            #     ## Time
            #     time_end_training = time.time()
            #     epoch_Online_Calculate_timeAccount = time_end_training - time_start_training_epoch # 计算时间
            #     epoch_Online_Communicate_timeAccount = self.online_comm_time_account  # 通信时间
            #     # offline time 不同epoch应该是相同的
            #     epoch_Online_timeAccounting = epoch_Online_Calculate_timeAccount + epoch_Online_Communicate_timeAccount
            #
            #     # epoch: [weight, Online_time_total, Online_time_comm]
            #     self.OVRModel_X.update({ str(self.n_iteration): [self.weightA + self.weightB, epoch_Online_timeAccounting, self.online_comm_time_account] })
            #
            # #######################################################################################################################################################

            ## 判断是否停止
            self.is_converged = self.check_converge_by_loss(loss)
            # if self.is_converged or self.n_iteration == self.max_iter:
            if self.n_iteration == self.max_iter:
                # self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice]) # 权重向量是一个列向量，需要横向划分
                if self.ratio is not None:
                    self.model_weights = np.hstack((self.weightA, self.weightB))
                    print("self.model_weights: ", self.model_weights)
                break

            self.n_iteration += 1

    def _generate_batch_data(self, X, y, batch_size):
        '''
        生成mini-batch数据集
        '''
        X_batch_list = []
        y_batch_list = []

        for i in range(len(y) // batch_size):
            X_batch_list.append(X[i * batch_size: i * batch_size + batch_size, :])
            y_batch_list.append(y[i * batch_size: i * batch_size + batch_size])
            self.batch_num.append(batch_size)

        if (len(y) % batch_size > 0):
            X_batch_list.append(X[len(y) // batch_size * batch_size:, :])
            y_batch_list.append(y[len(y) // batch_size * batch_size:])
            self.batch_num.append(len(y) % batch_size)

        return X_batch_list, y_batch_list

    def _distributed_generate_batch_data(self, X, y, batch_size, ratio):
        '''
        生成两部分,纵向划分的, mini-batch数据集.
        只划分特征矩阵,不划分标签向量y
        ratio: 决定划分到含有标签的一方的数据的比例,对划分的数量下取整,例如 0.8 * 63 -> 50
        '''
        X_batch_listA = []
        X_batch_listB = []
        y_batch_list = []

        self.indice = math.floor(ratio * X.shape[1])  # 纵向划分数据集，位于label一侧的特征数量

        for i in range(len(y) // batch_size):
            X_tmpA, X_tmpB = np.hsplit(X[i * batch_size: i * batch_size + batch_size, :], [self.indice])  # 纵向划分数据集
            X_batch_listA.append(X_tmpA)
            X_batch_listB.append(X_tmpB)
            y_batch_list.append(y[i * batch_size: i * batch_size + batch_size])
            self.batch_num.append(batch_size)

        if (len(y) % batch_size > 0):
            X_tmpA, X_tmpB = np.hsplit(X[len(y) // batch_size * batch_size:, :], [self.indice])
            # X_batch_list.append(X[len(y) // batch_size * batch_size:, :])
            X_batch_listA.append(X_tmpA)
            X_batch_listB.append(X_tmpB)
            y_batch_list.append(y[len(y) // batch_size * batch_size:])
            self.batch_num.append(len(y) % batch_size)

        return X_batch_listA, X_batch_listB, y_batch_list  # listA——持有label一侧，较多样本; listB——无label一侧

    def _distributed_generate_sparse_batch_data(self, X, y, batch_size, ratio):
        '''
        sparse*
        生成两部分,纵向划分的, mini-batch数据集.
        只划分特征矩阵,不划分标签向量y
        ratio: 决定划分到含有标签的一方的数据的比例,对划分的数量下取整,例如 0.8 * 63 -> 50
        '''
        X_batch_listA = []
        X_batch_listB = []
        y_batch_list = []

        self.indice = math.floor(ratio * X.shape[1])  # 纵向划分数据集，位于label一侧的特征数量

        X_PartyA, X_PartyB = np.hsplit(X[:, :], [self.indice])
        X_PartyA = lil_matrix(X_PartyA)
        X_PartyB = lil_matrix(X_PartyB)

        for i in range(len(y) // batch_size):
            # X_tmpA, X_tmpB = np.hsplit(X[i * batch_size : i * batch_size + batch_size, :], [self.indice]) # 纵向划分数据集
            X_batch_listA.append(X_PartyA[i * batch_size: i * batch_size + batch_size, :].tocsr())
            X_batch_listB.append(X_PartyB[i * batch_size: i * batch_size + batch_size, :].tocsr())
            y_batch_list.append(y[i * batch_size: i * batch_size + batch_size])
            self.batch_num.append(batch_size)

        if (len(y) % batch_size > 0):
            # X_tmpA, X_tmpB = np.hsplit(X[len(y) // batch_size * batch_size:, :], [self.indice])
            # X_batch_list.append(X[len(y) // batch_size * batch_size:, :])
            X_batch_listA.append(X_PartyA[len(y) // batch_size * batch_size:, :].tocsr())
            X_batch_listB.append(X_PartyB[len(y) // batch_size * batch_size:, :].tocsr())
            y_batch_list.append(y[len(y) // batch_size * batch_size:])
            self.batch_num.append(len(y) % batch_size)

        return X_batch_listA, X_batch_listB, y_batch_list  # listA——持有label一侧，较多样本; listB——无label一侧

    def _generate_batch_data_for_distributed_parts(self, X1, X2, y, batch_size):
        '''
        输入的数据就是两部分的
        目的是将这两部分横向ID对齐的数据 划分成一个个batch (可用于实验中的分别采样输入数据)
        ratio: 决定划分到含有标签的一方的数据的比例,对划分的数量下取整,例如 0.8 * 63 -> 50
        '''
        X_batch_listA = []
        X_batch_listB = []
        y_batch_list = []
        # self.indice = math.floor(ratio * X.shape[1]) # 纵向划分数据集，位于label一侧的特征数量

        for i in range(len(y) // batch_size):
            # X_tmpA = X1[i * batch_size : i * batch_size + batch_size, :]
            X_batch_listA.append(X1[i * batch_size: i * batch_size + batch_size, :])
            X_batch_listB.append(X2[i * batch_size: i * batch_size + batch_size, :])
            y_batch_list.append(y[i * batch_size: i * batch_size + batch_size])
            self.batch_num.append(batch_size)

        if (len(y) % batch_size > 0):
            # X_tmpA, X_tmpB = np.hsplit(X[len(y) // batch_size * batch_size:, :], [self.indice])
            # X_batch_list.append(X[len(y) // batch_size * batch_size:, :])
            X_batch_listA.append(X1[len(y) // batch_size * batch_size:, :])
            X_batch_listB.append(X2[len(y) // batch_size * batch_size:, :])
            y_batch_list.append(y[len(y) // batch_size * batch_size:])
            self.batch_num.append(len(y) % batch_size)

        return X_batch_listA, X_batch_listB, y_batch_list  # listA——持有label一侧，较多样本; listB——无label一侧

    def _generate_Sparse_batch_data_for_distributed_parts(self, X1, X2, y, batch_size):
        '''
        sparse* 输入的数据就是两部分的
        目的是将这两部分横向ID对齐的数据 划分成一个个batch (可用于实验中的分别采样输入数据)
        ratio: 决定划分到含有标签的一方的数据的比例,对划分的数量下取整,例如 0.8 * 63 -> 50
        '''
        X_batch_listA = []
        X_batch_listB = []
        y_batch_list = []
        X1 = lil_matrix(X1)
        X2 = lil_matrix(X2)
        # self.indice = math.floor(ratio * X.shape[1]) # 纵向划分数据集，位于label一侧的特征数量

        for i in range(len(y) // batch_size):
            # X_tmpA = X1[i * batch_size : i * batch_size + batch_size, :]
            X_batch_listA.append(X1[i * batch_size: i * batch_size + batch_size, :].tocsr())
            X_batch_listB.append(X2[i * batch_size: i * batch_size + batch_size, :].tocsr())
            y_batch_list.append(y[i * batch_size: i * batch_size + batch_size])
            self.batch_num.append(batch_size)

        if (len(y) % batch_size > 0):
            # X_tmpA, X_tmpB = np.hsplit(X[len(y) // batch_size * batch_size:, :], [self.indice])
            # X_batch_list.append(X[len(y) // batch_size * batch_size:, :])
            X_batch_listA.append(X1[len(y) // batch_size * batch_size:, :].tocsr())
            X_batch_listB.append(X2[len(y) // batch_size * batch_size:, :].tocsr())
            y_batch_list.append(y[len(y) // batch_size * batch_size:])
            self.batch_num.append(len(y) % batch_size)

        return X_batch_listA, X_batch_listB, y_batch_list  # listA——持有label一侧，较多样本; listB——无label一侧

    def predict(self, x_test, y_test):
        # z = np.dot(x_test, self.model_weights.T)
        # z = x_test.dot(self.model_weights.T)
        # z = self._cal_z()
        if self.data_tag == 'sparse':
            z = x_test.dot(self.model_weights.T)  # np.dot(features, weights.T)
        elif self.data_tag == None:
            z = np.dot(x_test, self.model_weights.T)

        y = self._compute_sigmoid(z)

        score = 0
        for i in range(len(y)):
            if y[i] >= 0.5:
                y[i] = 1
            else:
                y[i] = 0
            if y[i] == y_test[i]:
                score += 1
            else:
                pass
        rate = score / len(y)
        print("Predict precision: ", rate)

    def predict_distributed(self, x_test1, x_test2, y_test):
        # z = np.dot(x_test, self.model_weights.T)
        # z = x_test.dot(self.model_weights.T)
        # z = self._cal_z()
        x_test = np.hstack((x_test1, x_test2))
        if self.data_tag == 'sparse':
            z = x_test.dot(self.model_weights.T)  # np.dot(features, weights.T)
        elif self.data_tag == None:
            z = np.dot(x_test, self.model_weights.T)

        y = self._compute_sigmoid(z)

        score = 0
        for i in range(len(y)):
            if y[i] >= 0.5:
                y[i] = 1
            else:
                y[i] = 0
            if y[i] == y_test[i]:
                score += 1
            else:
                pass
        print("score: ", score)
        print("len(y): ", len(y))
        rate = float(score) / float(len(y))
        print("Predict precision: ", rate)
        return rate

    def predict_distributed_OVR(self, x_test1, x_test2):
        x_test = np.hstack((x_test1, x_test2))
        if self.data_tag == 'sparse':
            z = x_test.dot(self.model_weights.T)  # np.array类型（此处其实需要严谨一点，避免数据类型不清晰影响后续运算）
            if not isinstance(z, np.ndarray):
                z = z.toarray()
        elif self.data_tag == None:
            z = np.dot(x_test, self.model_weights.T)

        y = self._compute_sigmoid(z)

        return y.reshape(1, -1)  # list(y.reshape((1, -1)))

    def OVRClassifier(self, X_train1, X_train2, X_test1, X_test2, Y_train, Y_test):
        """
        OVR: one vs rest 多分类
        """
        # indice_littleside = X_train1.shape[1]
        self.indice = X_train1.shape[1]
        instances_count = X_train1.shape[0]
        label_lst = list(set(Y_train))  # 多分类的所有标签值集合
        print('数据集标签值集合: ', label_lst)
        prob_lst = []  # 存储每个二分类模型的预测概率值

        """ OVR Model Training """
        # # batch 数据生成
        # X_batch_listA, X_batch_listB, y_batch_list = self._generate_batch_data_for_distributed_parts(X_train1, X_train2,
        #                                                                                 Y_train, self.batch_size)
        # self.weightA, self.weightB = np.hsplit(self.model_weights, [self.indice]) # 权重向量是一个列向量，需要横向划分

        for i in range(len(label_lst)):
            # 转换标签值为二分类标签值
            pos_label = label_lst[i]  # 选定正样本的标签
            print("Label: ", pos_label)

            # def label_reset_OVR(arr):
            #     """ 依次将标签i设置为正样本, 其他为负样本 """
            #     # global pos_label
            #     return np.where(arr == pos_label, 1, 0)

            # y_batch_list = list(map(label_reset_OVR, y_batch_list))

            Y_train_new = np.where(Y_train == pos_label, 1, 0)  # 满足条件则为正样本1，否则为负样本0
            # Y_test_new = np.where(Y_test == pos_label, 1, 0)
            # print(Y_train_new)
            self.fit_model_distributed_input(X_train1, X_train2, Y_train_new, X_train1.shape[0],
                                             X_train1.shape[1])

            # self.OVRModel_Agg.update({pos_label: self.OVRModel_X})  # 存储 ############################################################################

            prob = self.predict_distributed_OVR(X_test1, X_test2)  # 第i个二分类模型在测试数据集上，每个样本取正标签的概率（用决策函数值作为概率值）
            prob = np.where(prob > 0, prob, 0).flatten()
            prob_lst.append(prob.tolist())
            # print(prob_lst)

        # 多分类模型预测
        print(np.shape(prob_lst))
        y_predict = []  # 存储多分类的预测标签值
        prob_array = np.asarray(prob_lst).T  # (n_samples, n_classes)
        print(prob_array.shape)
        print(type(prob_array))
        print(type(prob_array[0]))
        print(type(prob_array[0][0]))

        for i in range(len(Y_test)):
            temp = list(prob_array[i])
            index = temp.index(max(temp))
            # print(index)
            y_predict.append(label_lst[index])
        # print(y_predict)
        # 模型预测准确率
        score = 0
        for i in range(len(y_predict)):
            if y_predict[i] == Y_test[i]:
                score += 1
            else:
                pass
        rate = score / len(y_predict)
        print("Predict precision: ", rate)
        return rate

########################################################################################################################
def read_data():
    # from sklearn.datasets import load_breast_cancer
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import MinMaxScaler, StandardScaler, normalize
    mm = MinMaxScaler()
    ss = StandardScaler()

    # cancers = load_breast_cancer()
    # X = cancers.data       #获取特征值
    # Y = cancers.target     #获取标签
    # np.savetxt("/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/logistic_regression/X1.txt", X, delimiter=',') #, fmt='%.2f')
    # np.savetxt("/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/logistic_regression/Y1.txt", Y, delimiter=',') #, fmt='%.2f')
    # print("saving...")
    X = np.loadtxt("/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/logistic_regression/X.txt",
                   delimiter=',')  # , dtype = float)
    Y = np.loadtxt("/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/logistic_regression/Y.txt",
                   delimiter=',')  # , dtype = float)
    # X = normalize(X,'l2')
    X = ss.fit_transform(X)
    print(X.shape)  # 查看特征形状
    print(Y.shape)  # 查看标签形状
    x_train, x_test, y_train, y_test = train_test_split(X, Y, test_size=0.2, shuffle=False)
    return x_train, y_train, x_test, y_test


def read_sampling_data():
    from sklearn.datasets import load_svmlight_file
    import os
    from sklearn.preprocessing import MinMaxScaler, StandardScaler, normalize
    mm = MinMaxScaler()
    ss = StandardScaler()

    dataset_file_name = 'splice'
    train_file_name = 'splice_train.txt'
    test_file_name = 'splice_test'
    main_path = '/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/'

    # dataset_file_name = 'a6a'
    # train_file_name = 'a6a.txt'
    # test_file_name = 'a6a.t'
    # main_path = '/Users/zbz/data/'
    train_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, train_file_name))
    test_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, test_file_name))
    X_train = train_data[0]
    Y_train = train_data[1].astype(int)
    X_test = test_data[0]
    Y_test = test_data[1].astype(int)
    print(type(X_train))  # 1000 * 60
    # print(Y_train[0]) # 1000 * 1

    # 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
    if -1 in Y_train:
        Y_train[Y_train == -1] = 0
        Y_test[Y_test == -1] = 0
    # print(Y_train)
    # print(Y_test)

    # #a6a a7a
    # X_train = X_train.todense().A
    # X_train = np.hstack( (X_train, np.zeros(X_train.shape[0]).reshape(-1, 1)) )
    # return ss.fit_transform(X_train), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array

    # #splice
    # return ss.fit_transform(X_train.todense().A), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array
    # # return X_train.todense().A, Y_train, X_test.todense().A, Y_test # matrix转array

    # sparse matrix (splice)
    # return ss.fit_transform(X_train), Y_train, ss.fit_transform(X_test), Y_test # matrix转array
    return X_train, Y_train, X_test, Y_test  # matrix转array

    # X = np.loadtxt('/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/splice/X_train_sketch.txt',
    #                 delimiter=',') #, dtype = float)


def read_encoded_data():
    from sklearn.datasets import load_svmlight_file
    import os
    from sklearn.preprocessing import MinMaxScaler, StandardScaler, normalize
    mm = MinMaxScaler()
    ss = StandardScaler()

    dataset_file_name = 'splice'
    train_file_name = 'splice_train.txt'
    test_file_name = 'splice_test'
    main_path = '/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/'

    # dataset_file_name = 'a6a'
    # train_file_name = 'a6a.txt'
    # test_file_name = 'a6a.t'
    # main_path = '/Users/zbz/data/'
    train_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, train_file_name))
    test_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, test_file_name))
    # X_train = train_data[0]
    Y_train = train_data[1].astype(int)
    # X_test = test_data[0]
    Y_test = test_data[1].astype(int)
    # print(type(X_train)) # 1000 * 60
    # print(Y_train[0]) # 1000 * 1

    # 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
    if -1 in Y_train:
        Y_train[Y_train == -1] = 0
        Y_test[Y_test == -1] = 0
    print(Y_train)
    print(Y_test)

    # #a6a a7a
    # X_train = X_train.todense().A
    # X_train = np.hstack( (X_train, np.zeros(X_train.shape[0]).reshape(-1, 1)) )
    # return ss.fit_transform(X_train), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array

    # #splice
    # return ss.fit_transform(X_train.todense().A), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array
    # # return X_train.todense().A, Y_train, X_test.todense().A, Y_test # matrix转array
    print("loading dataset...")
    X_train = np.loadtxt(
        "/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/splice/distrubuted/encoded/X_encoded_train37.txt",
        delimiter=',', dtype=int)
    X_test = np.loadtxt(
        "/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/splice/distrubuted/encoded/X_encoded_test37.txt",
        delimiter=',', dtype=int)
    # X = normalize(X,'l2')
    # X_train = ss.fit_transform(X_train)
    print(X_train.shape)  # 查看特征形状
    print(type(X_train), type(X_test))
    print(X_test.shape)  # 查看测试特征形状

    # print("Constructing sparse matrix...") # 使用COO格式高效创建稀疏矩阵, 以线性时间复杂度转化为CSR格式用于高效的矩阵乘法或转置运算.
    # X_train = lil_matrix(X_train)
    # # X_train.tocsr()
    # X_test = lil_matrix(X_test)
    # # X_test.tocsr()
    # print(type(X_train), type(X_test))

    return X_train, Y_train, X_test, Y_test  # matrix转array


def read_distributed_encoded_data():
    from sklearn.datasets import load_svmlight_file
    import os
    from sklearn.preprocessing import MinMaxScaler, StandardScaler, normalize
    mm = MinMaxScaler()
    ss = StandardScaler()

    dataset_file_name = 'splice'
    train_file_name = 'splice_train.txt'
    test_file_name = 'splice_test'
    main_path = PATH_DATA

    # dataset_file_name = 'a6a'
    # train_file_name = 'a6a.txt'
    # test_file_name = 'a6a.t'
    # main_path = '/Users/zbz/data/'
    train_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, train_file_name))
    test_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, test_file_name))
    # X_train = train_data[0]
    Y_train = train_data[1].astype(int)
    # X_test = test_data[0]
    Y_test = test_data[1].astype(int)
    # print(type(X_train)) # 1000 * 60
    # print(Y_train[0]) # 1000 * 1

    # 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
    if -1 in Y_train:
        Y_train[Y_train == -1] = 0
        Y_test[Y_test == -1] = 0
    # print(Y_train)
    # print(Y_test)

    # #a6a a7a
    # X_train = X_train.todense().A
    # X_train = np.hstack( (X_train, np.zeros(X_train.shape[0]).reshape(-1, 1)) )
    # return ss.fit_transform(X_train), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array

    # #splice
    # return ss.fit_transform(X_train.todense().A), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array
    # # return X_train.todense().A, Y_train, X_test.todense().A, Y_test # matrix转array
    print("loading dataset...")

    dataset_file_name = 'splice/distrubuted/encoded/'
    train_file_name1 = 'X1_encoded_train37.txt'
    train_file_name2 = 'X2_encoded_train37.txt'
    test_file_name1 = 'X1_encoded_test37.txt'
    test_file_name2 = 'X2_encoded_test37.txt'
    main_path = PATH_DATA
    X_train1 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name1),
                          delimiter=',')  # , dtype = float)
    X_train2 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name2),
                          delimiter=',')  # , dtype = float)
    X_test1 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name1), delimiter=',')  # , dtype = float)
    X_test2 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name2), delimiter=',')  # , dtype = float)
    # X = normalize(X,'l2')
    # X_train = ss.fit_transform(X_train)
    print(X_train1.shape)  # 查看特征形状
    print(type(X_train1), type(X_test1))
    print(X_test1.shape)  # 查看测试特征形状

    # print("Constructing sparse matrix...") # 使用COO格式高效创建稀疏矩阵, 以线性时间复杂度转化为CSR格式用于高效的矩阵乘法或转置运算.
    # X_train = lil_matrix(X_train)
    # # X_train.tocsr()
    # X_test = lil_matrix(X_test)
    # # X_test.tocsr()
    # print(type(X_train), type(X_test))

    return X_train1, X_train2, Y_train, X_test1, X_test2, Y_test  # matrix转array


def read_distributed_squeeze_data():
    ## countsketch
    from sklearn.datasets import load_svmlight_file
    import os
    global flag
    flag = "sketch"

    dataset_file_name = 'DailySports'
    train_file_name = 'DailySports_train.txt'
    test_file_name = 'DailySports_test.txt'
    main_path = PATH_DATA
    # main_path = '/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/'

    # dataset_file_name = 'a6a'
    # train_file_name = 'a6a.txt'
    # test_file_name = 'a6a.t'
    # main_path = '/Users/zbz/data/'
    train_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, train_file_name))
    test_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, test_file_name))
    # X_train = train_data[0]
    Y_train = train_data[1].astype(int)
    # X_test = test_data[0]
    Y_test = test_data[1].astype(int)
    # print(type(X_train)) # 1000 * 60
    # print(Y_train[0]) # 1000 * 1

    ##### 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
    # if -1 in Y_train:
    #     Y_train[Y_train == -1] = 0
    #     Y_test[Y_test == -1] = 0

    # 针对SprotsNews, 多分类修改成二分类
    print("processing dataset...")
    # Y_train[Y_train != 1] = 0
    # Y_test[Y_test != 1] = 0

    # #a6a a7a
    # X_train = X_train.todense().A
    # X_train = np.hstack( (X_train, np.zeros(X_train.shape[0]).reshape(-1, 1)) )
    # return ss.fit_transform(X_train), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array

    # #splice
    # return ss.fit_transform(X_train.todense().A), Y_train, ss.fit_transform(X_test.todense().A), Y_test # matrix转array
    # # return X_train.todense().A, Y_train, X_test.todense().A, Y_test # matrix转array
    print("loading dataset...")

    dataset_file_name = 'DailySports/portion37_pminhash/sketch1024/countsketch/'
    train_file_name1 = 'X1_squeeze_train37_Countsketch.txt'
    train_file_name2 = 'X2_squeeze_train37_Countsketch.txt'
    test_file_name1 = 'X1_squeeze_test37_Countsketch.txt'
    test_file_name2 = 'X2_squeeze_test37_Countsketch.txt'
    # main_path = '/Users/zbz/code/vscodemac_python/hetero_sshe_logistic_regression/data/'
    main_path = PATH_DATA
    X_train1 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name1),
                          delimiter=',')  # , dtype = float)
    X_train2 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name2),
                          delimiter=',')  # , dtype = float)
    X_test1 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name1), delimiter=',')  # , dtype = float)
    X_test2 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name2), delimiter=',')  # , dtype = float)
    # X = normalize(X,'l2')
    # X_train = ss.fit_transform(X_train)
    print(X_train1.shape)  # 查看特征形状
    print(type(X_train1), type(X_test1))
    print(X_test1.shape)  # 查看测试特征形状

    # print("Constructing sparse matrix...") # 使用COO格式高效创建稀疏矩阵, 以线性时间复杂度转化为CSR格式用于高效的矩阵乘法或转置运算.
    # X_train = lil_matrix(X_train)
    # # X_train.tocsr()
    # X_test = lil_matrix(X_test)
    # # X_test.tocsr()
    # print(type(X_train), type(X_test))

    return X_train1, X_train2, Y_train, X_test1, X_test2, Y_test  # matrix转array




def read_distributed_data_raw_or_sketch(dataset_name, raw_or_sketch, kernel_method, portion, sampling_k, ovr,
                                        countsketch_, bbitmwhash_, scalering_raw):
    """
    Desc:
    ----
    load data.

    Para:
    ----
    dataset_name: name of input dataset
    raw_or_sketch: input data - raw data or sketch data
    kernel_method: pminhash / 0bitcws / rff / poly
    portion: vertically partition scale
    sampling_k: sampling times(k)
    ovr:  one vs rest strategy
    scalering_raw: scalering raw data or not
    """
    ## countsketch
    from sklearn.datasets import load_svmlight_file
    from sklearn.preprocessing import MinMaxScaler, StandardScaler, MaxAbsScaler, Normalizer, RobustScaler
    mm = MinMaxScaler()
    ss = StandardScaler()
    na = Normalizer()
    ma = MaxAbsScaler()
    rs = RobustScaler()

    main_path = PATH_DATA
    dataset_file_name = dataset_name
    train_file_name = dataset_name + '_train.txt'
    test_file_name = dataset_name + '_test.txt'
    # dataset_file_name = 'DailySports'
    # train_file_name = 'DailySports_train.txt'
    # test_file_name = 'DailySports_test.txt'

    """
    读取数据集的 Label: Y_train, Y_test
    """
    type_flag = "dense"  # sparse
    print("loading dataset...")
    train_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, train_file_name))
    test_data = load_svmlight_file(os.path.join(main_path, dataset_file_name, test_file_name))

    Y_train = train_data[1].astype(int)
    Y_test = test_data[1].astype(int)

    """
    数据集抽取(对于部分较大数据集),
    将训练集抽取一部分
    其余数据集: 只是返回原始的训练集和训练集标签
        sketch部分:只需要抽取Y
        raw部分:需要X和Y都抽取
    返回的结果: numpy格式的X_train和Y_train (抽取后的或没有经过抽取的)
    (后面再写, 最好是采样和raw 抽取的是同一部分样本)
    """
    X_train, X_test, Y_train = dataset_selector(dataset_name, train_data, test_data, Y_train)
    # X_test, Y_test = dataset_selector(dataset_name, test_data, Y_test)

    """
    标签检查和重构
    """
    ##### 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
    # if -1 in Y_train:
    #     Y_train[Y_train == -1] = 0
    #     Y_test[Y_test == -1] = 0

    print("processing dataset...")
    if ovr == "bin":
        """ 二分类数据集的标签处理为: 1 0 分类 """
        if -1 in Y_train:
            # 判断标签是(1;-1)还是 (1;0), 将-1的标签全部转化成0标签
            Y_train[Y_train != 1] = 0
            Y_test[Y_test != 1] = 0

    """
    确定最终的目标数据集路径
    """
    if portion == "37":
        partition = 3 / 10
    elif portion == "28":
        partition = 2 / 10
    elif portion == "19":
        partition = 1 / 10
    elif portion == "46":
        partition = 4 / 10
    elif portion == "55":
        partition = 5 / 10
    else:
        raise ValueError

    """
    一个不知道怎么处理的参数: gamma_scale
    """
    gamma_scale = -1

    if raw_or_sketch == "sketch" and kernel_method in ["pminhash", "0bitcws"]:

        if countsketch_ == 0 and bbitmwhash_ == 0:
            ## 目前这里跑实验的时候, 这两个值不能同时为0, 否则没有意义
            raise ValueError("[error] b(bbitmwhash) and c(countsketch) equals to 0 at the same time!")

        """ 获取需要读取的sketch的相对路径 """
        portion_kernel_method = "portion" + portion + "_" + kernel_method
        sketch_sample = "sketch" + sampling_k

        # dataset_file_name = 'kits/portion37_pminhash/sketch1024/countsketch/'
        # train_file_name1 = 'X1_squeeze_train37_Countsketch.txt'
        # train_file_name2 = 'X2_squeeze_train37_Countsketch.txt'
        # test_file_name1 = 'X1_squeeze_test37_Countsketch.txt'
        # test_file_name2 = 'X2_squeeze_test37_Countsketch.txt'

        if kernel_method == "pminhash" and countsketch_:
            """ sketch + countsketch """
            dataset_file_name = os.path.join(dataset_name, portion_kernel_method, sketch_sample,
                                             "countsketch" + "_" + str(countsketch_))
            train_file_name1 = 'X1_squeeze_train37.txt'
            train_file_name2 = 'X2_squeeze_train37.txt'
            test_file_name1 = 'X1_squeeze_test37.txt'
            test_file_name2 = 'X2_squeeze_test37.txt'

        elif kernel_method == "0bitcws" and bbitmwhash_:
            """ sketch + bbitmwhash """
            dataset_file_name = os.path.join(dataset_name, portion_kernel_method, sketch_sample,
                                             "bbitmwhash" + "_" + str(2 ** bbitmwhash_))
            train_file_name1 = 'X1_squeeze_train37.txt'
            train_file_name2 = 'X2_squeeze_train37.txt'
            test_file_name1 = 'X1_squeeze_test37.txt'
            test_file_name2 = 'X2_squeeze_test37.txt'

        else:
            """ sketch only 毫无意义的入口, 我也不知道为什么保留到现在"""
            dataset_file_name = os.path.join(dataset_name, portion_kernel_method, sketch_sample)
            train_file_name1 = 'X1_train_samples.txt'
            train_file_name2 = 'X2_train_samples.txt'
            test_file_name1 = 'X1_test_samples.txt'
            test_file_name2 = 'X2_test_samples.txt'
            raise ValueError("Attempt to read some meaningless data as model training data.")

        X_train1 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name1),
                              delimiter=',')  # , dtype = float) # <class 'numpy.float64'>
        X_train2 = np.loadtxt(os.path.join(main_path, dataset_file_name, train_file_name2),
                              delimiter=',')  # , dtype = float)
        X_test1 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name1),
                             delimiter=',')  # , dtype = float)
        X_test2 = np.loadtxt(os.path.join(main_path, dataset_file_name, test_file_name2),
                             delimiter=',')  # , dtype = float)

        # print(X_train1) # [[0. 1. 0. ... 1. 0. 1.]]
        # print(type(X_train1[0][0])) # <class 'numpy.float64'>



    elif raw_or_sketch == "sketch" and kernel_method in ["rff", "poly"]:
        # X_test = test_data[0].todense().A
        X_test = X_test.todense().A

        # 输入的X_train是原数据集(如果数据集过大, dataset_selector中会随机抽取一部分, 具体见dataset_selector函数);
        # 如果抽取了X_train, Y_train也会对应着抽取
        X_train1, X_train2, Y_train, X_test1, X_test2, Y_test, gamma_scale = dataSketch_generator_RBFandPolyKernel(
            X_train, X_test, Y_train, Y_test, kernel_method, sampling_k, partition)


        # 加入归一化（两方合并后归一化）
        # X_train = np.hstack((X_train1, X_train2))
        # X_test = np.hstack((X_test1, X_test2))
        # X_train = mm.fit_transform(X_train)
        # X_test = mm.fit_transform(X_test)

        # k = X_train.shape[1] # 总特征数
        # # partition = 3/10
        # k1 = np.floor(k * partition).astype(int) # X1的特征数
        # X_train1, X_train2 = X_train[:,0:k1], X_train[:,k1:]

        # k = X_test.shape[1]
        # # partition = 3/10
        # k1 = np.floor(k * partition).astype(int)
        # X_test1, X_test2 = X_test[:,0:k1], X_test[:,k1:]


        # 加入归一化（两方各自归一化）
        # X_train1 = mm.fit_transform(X_train1)
        # X_train2 = mm.fit_transform(X_train2)
        # X_test1 = mm.fit_transform(X_test1)
        # X_test2 = mm.fit_transform(X_test2)



    elif raw_or_sketch == "raw":  # and type_flag == "dense":
        """ 对于 Raw data, 直接读入原始数据, 然后按照比例 portion 分成两个部分, 作为两方数据 """
        print("Try to read Raw data...")

        scalering_list = ["mm", "ss", "na", "ma", "rs"]
        if scalering_raw in scalering_list:
            """ from sklearn.preprocessing import MinMaxScaler, StandardScaler, MaxAbsScaler, Normalizer, RobustScaler
                mm = MinMaxScaler()
                ss = StandardScaler()
                na = Normalizer()
                ma = MaxAbsScaler()
                rs = RobustScaler() 
            """
            scaler = eval(scalering_raw)
            X_train = X_train.todense().A
            X_train = scaler.fit_transform(X_train)

            # X_test = test_data[0].todense().A
            X_test = X_test.todense().A
            X_test = scaler.fit_transform(X_test)

        elif scalering_raw == "nope":
            print("To dense, [nope]")
            # X_train = train_data[0].todense().A
            X_train = X_train.todense().A
            # X_train = mm.fit_transform(X_train)
            X_test = X_test.todense().A
            # dengxia
            # X_test = mm.fit_transform(X_test)

        # X_train
        k = X_train.shape[1]  # 总特征数
        # partition = 3/10
        k1 = np.floor(k * partition).astype(int)  # X1的特征数
        X_train1, X_train2 = X_train[:, 0:k1], X_train[:, k1:]

        # X_test
        k = X_test.shape[1]
        # partition = 3/10
        k1 = np.floor(k * partition).astype(int)
        X_test1, X_test2 = X_test[:, 0:k1], X_test[:, k1:]


    elif raw_or_sketch != "raw":  # and type_flag == "sparse":
        # raw且需要保持稀疏还得改
        pass

    print("X_train1 type: ", type(X_train1))  # 1000 * 60
    print("X_train1 shape: ", X_train1.shape)
    print("X_train2 type: ", type(X_train2))  # 1000 * 60
    print("X_train2 shape: ", X_train2.shape)
    print("X_test1 type: ", type(X_test1))  # 1000 * 60
    print("X_test1 shape: ", X_test1.shape)
    print("X_test2 type: ", type(X_test2))  # 1000 * 60
    print("X_test2 shape: ", X_test2.shape)
    print("Y_train type: ", type(Y_train))
    print("Y_test type: ", type(Y_test))

    return X_train1, X_train2, Y_train, X_test1, X_test2, Y_test, gamma_scale

########################################################################################################################


# if __name__ == "__main__":
#
#     """ secureml test"""
#     dataset_name = "DailySports"  # cifar10
#     portion = "37"  # 19 / 28 / 37 / 46 / 55
#     raw_or_sketch = "sketch"  # "raw" / "sketch"
#     kernel_method = "rff"  # pminhash / 0bitcws / rff / poly
#     sampling_k = "1024"
#     countsketch_ = 2
#     bbitmwhash_ = 2  # 这里是b值, 读取文件还需要 2^b
#
#     ovr = "ovr"  # bin 二分类 / ovr 多分类
#     scalering_raw = "mm"  # mm / ss / na / ma / rs / null
#     converge_ondecide = "off"  # on / off
#
#
#     alpha = 0.01
#     max_iter = 40  # 200
#     lambda_para = 0.01
#     batch_size = 64
#     c = 1
#
#     sigmoid_func = "linear"  # linear approximation 一次函数 / cube approximation 三次函数 / segmentation approximation 分段函数 / original sigmoid 原激活函数
#     #########
#     Writing_to_Final_Logfile = False  # 是否将本次实验结果写入此数据集的结果汇总中
#
#
#     X_train1, X_train2, Y_train, X_test1, X_test2, Y_test, gamma_scale = read_distributed_data_raw_or_sketch(
#         dataset_name, raw_or_sketch,
#         kernel_method, portion, sampling_k, ovr, countsketch_, bbitmwhash_, scalering_raw)
#
#     if raw_or_sketch == "sketch" and kernel_method in ["rff", "poly"] and gamma_scale == -1:
#         raise ValueError("gamma_scale not updated.")
#
#     ########## 权重初始化 ##########
#     np.random.seed(100)
#
#     # 纵向划分分布式
#     weight_vector = np.zeros(X_train1.shape[1] + X_train2.shape[1]).reshape(1, -1)
#     # print(weight_vector)
#
#     LogisticRegressionModel = LogisticRegression(weight_vector=weight_vector, batch_size=batch_size,
#                                                  max_iter=max_iter, alpha=alpha, eps=1e-5, ratio=0.7, penalty=None,
#                                                  lambda_para=lambda_para, data_tag='sparse', c=c)
#
#     ########## 训练 ##########
#     import time
#
#     time_start = time.time()
#
#     # 理想集中和伪分布式
#     # LogisticRegressionModel.fit_model(X_data, y_data, X_data.shape[0])
#
#     # 纵向划分分布式
#     indice_littleside = X_train1.shape[1]  # 纵向A的特征数量,
#     if ovr == "bin":
#         LogisticRegressionModel.fit_model_distributed_input(X_train1, X_train2, Y_train, X_train1.shape[0],
#                                                             indice_littleside)
#         LogisticRegressionModel.predict_distributed(X_test1, X_test2, Y_test)
#     elif ovr == "ovr":
#         LogisticRegressionModel.OVRClassifier(X_train1, X_train2, X_test1, X_test2, Y_train, Y_test)
#     time_end = time.time()
#     print('time cost: ', time_end - time_start, 's')
#
#     print("alpha ", alpha)
#     print("max_iter ", max_iter)
#     print("lambda_para ", lambda_para)
#     print("batch_size ", batch_size)
#     print("c ", c)
#
#     # plt.plot(LogisticRegressionModel.loss_history)
#     # plt.show()
#
#     ########## 测试 ##########
#     # 理想集中和伪分布式
#     # LogisticRegressionModel.predict(X_test, y_test)
#     # 纵向划分分布式
#     # LogisticRegressionModel.predict_distributed(X_test1, X_test2, Y_test)

########################################################################################################################


def No_MPC_Model(weight_vector, batch_size, max_iter, alpha, eps, ratio, penalty, lambda_para, data_tag, C, multi_class, X_train1, X_train2, X_test1, X_test2, Y_train, Y_test, log_path):
    time_start = time.time()
    LogisticRegressionModel = LogisticRegression(weight_vector=weight_vector, batch_size=batch_size,
                                                 max_iter=max_iter, alpha=alpha, eps=eps, ratio=ratio, penalty=penalty,
                                                 lambda_para=lambda_para, data_tag=data_tag, c=C, ovr=multi_class)
    if multi_class == "bin":
        LogisticRegressionModel.fit_model_distributed_input(X_train1, X_train2, Y_train, X_train1.shape[0], X_train1.shape[1])
        acc = LogisticRegressionModel.predict_distributed(X_test1, X_test2, Y_test)
    elif multi_class == "ovr":
        acc = LogisticRegressionModel.OVRClassifier(X_train1, X_train2, X_test1, X_test2, Y_train, Y_test)
    else:
        raise ValueError("Wrong multi_class value.")
    time_end = time.time()

    #     alpha = 0.01
    #     batch_size = 64
    #     max_iter = 40  # 200
    #     lambda_para = 0.01
    #     C = 1
    message = "time cost={}s\nalpha={}\nbatch_size={}\nmax_iter={}\nlambda_para={}\nC={}\n".format(time_end - time_start, alpha, batch_size, max_iter, lambda_para, C)
    message += "Accuracy:{}\n".format(acc)
    with open(log_path, 'a') as f:
        f.write(message)
        f.write("========================END=========================\n\n\n")




if __name__ == "__main__":

    message = "========================No Secure Logistic Regression Model=========================\n"
    datetime = time.strftime("%Y-%m-%d-%H_%M_%S", time.localtime(time.time()))
    message += datetime

##################数据集参数####################
    dataset_name = "DailySports"  # cifar10
    portion = "37"  # 19 / 28 / 37 / 46 / 55
    raw_or_sketch = "sketch"  # "raw" / "sketch"
    kernel_method = "rff"  # pminhash / 0bitcws / rff / poly
    sampling_k = "1024"
    countsketch = 2
    bbitmwhash = 2  # 这里是b值, 读取文件还需要 2^b
    scalering_raw = "mm"  # 原数据集归一化方法 mm / ss / na / ma / rs / null
    converge_ondecide = "off"  # on / off
    multi_class = 'ovr'  # 二分类bin还是多分类ovr
    sigmoid_func = "linear"  # linear approximation 一次函数 / cube approximation 三次函数 / segmentation approximation 分段函数 / original sigmoid 原激活函数

    mes = "Dataset={}; Portion={}\n".format(dataset_name, portion)
    if raw_or_sketch == "sketch":
        mes += "kernel_method={}\nsampling_k={}\n".format(kernel_method, sampling_k)
        if kernel_method == "pminhash":
            mes += "countsketch={}\n".format(countsketch)
        elif kernel_method == "0bitcws":
            mes += "bbitminwisehash={}\n".format(bbitmwhash)

    else:
        mes += "Raw data Training\n"
    mes += "Other Dataset parameters:\nscalering_raw={}\nconverge_ondecide={}\nmulti_class={}\n".format(scalering_raw, converge_ondecide, multi_class)
    message += mes


#############基本不会改动的参数################
    eps = 1e-5
    ratio = 0.7
    penalty = None
    data_tag = 'sparse'

    mes = "Parameters usually fixed:\neps={}\nratio={}\npenalty={}\ndata_tag={}\n".format(eps, ratio, penalty, data_tag)
    message += mes

#############需要频繁改动的模型参数##############

    alpha = 0.01
    batch_size = 64
    max_iter = 100  # 200
    lambda_para = 0.01
    C = 1

    # mes = "=============Tunable Parameters=============\n"
    # mes += "alpha={}\n".format(alpha)
    # mes += "batch_size={}\n".format(batch_size)
    # mes += "max_iter={}\n".format(max_iter)
    # mes += "lambda_para={}\n".format(lambda_para)
    # mes += "C={}\n".format(C)
    # message += mes

    # #########
    # Writing_to_Final_Logfile = False  # 是否将本次实验结果写入此数据集的结果汇总中

    # 数据集训练前的处理
    X_train1, X_train2, Y_train, X_test1, X_test2, Y_test, gamma_scale = read_distributed_data_raw_or_sketch(
        dataset_name, raw_or_sketch,
        kernel_method, portion, sampling_k, multi_class, countsketch, bbitmwhash, scalering_raw)

    if raw_or_sketch == "sketch" and kernel_method in ["rff", "poly"]:
        mes = "gamma_scale={}\n".format(gamma_scale)
        message += mes

    if raw_or_sketch == "sketch" and kernel_method in ["rff", "poly"] and gamma_scale == -1:
        raise ValueError("gamma_scale not updated.")

    # 日志文件存储
    if raw_or_sketch == "sketch":
        if kernel_method == "pminhash":
            logname = dataset_name + "_" + portion + "_" + kernel_method + sampling_k + "_" + str(countsketch) + ".txt"
        elif kernel_method == "0bitcws":
            logname = dataset_name + "_" + portion + "_" + kernel_method + sampling_k + "_" + str(2**bbitmwhash) + ".txt"
        else:
            # rff, poly
            logname = dataset_name + "_" + portion + "_" + kernel_method + sampling_k + ".txt"
    else:
        logname = dataset_name + "_raw_" + ".txt"

    with open(os.path.join(PATH_FILE, logname), 'a') as f:
        f.write(message)
        f.write("-----------------------------------\n")

    ########## 权重初始化 ##########
    np.random.seed(100)
    weight_vector = np.zeros(X_train1.shape[1] + X_train2.shape[1]).reshape(1, -1)
    # print(weight_vector)

    ######### 模型训练与测试 ########
    p = Pool(5)
    batch_size_lst = []
    alpha_lst = []
    lambda_para_lst = []
    C_lst = []

    for batch_size in batch_size_lst:
        for alpha in alpha_lst:
            for lambda_para in lambda_para_lst:
                for C in C_lst:
                    p.apply_async(No_MPC_Model, args=(weight_vector, batch_size, max_iter, alpha, eps, ratio, penalty, lambda_para, data_tag, C, multi_class, X_train1, X_train2, X_test1, X_test2, Y_train, Y_test))
