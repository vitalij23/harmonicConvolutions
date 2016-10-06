'''Brute force rotational losses'''

import os
import sys
import time

import numpy as np

'''MNIST tests'''

'''Test the gConv script'''

import os
import sys
import time

import cv2
import numpy as np
import scipy.linalg as scilin
import scipy.ndimage.interpolation as sciint
import tensorflow as tf

import input_data

from rotated_conv import *
from matplotlib import pyplot as plt
from spatial_transformer import transformer

##### MODELS #####

def conv_Z(x, weights, biases, drop_prob, n_filters, n_classes):
	# Store layers weight & bias
	fm = []
	# Reshape input picture
	x = tf.reshape(x, shape=[-1, 28, 28, 1])
	
	# Convolution Layer
	cv1 = conv2d(x, weights['w1'], biases['b1'], name='gc1')
	fm.append(cv1)
	mp1 = tf.nn.relu(maxpool2d(cv1, k=2))
	fm.append(mp1)
	
	# Convolution Layer
	cv2 = conv2d(mp1, weights['w2'], biases['b2'], name='gc2')
	fm.append(cv2)
	mp2 = tf.nn.relu(maxpool2d(cv2, k=2))
	fm.append(mp2)

	# Fully connected layer
	fc3 = tf.reshape(mp2, [-1, weights['w3'].get_shape().as_list()[0]])
	fc3 = tf.nn.bias_add(tf.matmul(fc3, weights['w3']), biases['b3'])
	fc3 = tf.nn.relu(fc3)
	# Apply Dropout
	fc3 = tf.nn.dropout(fc3, drop_prob)
	
	# Output, class prediction
	out = tf.nn.bias_add(tf.matmul(fc3, weights['out']), biases['out'])
	return out, fm

def transformer_loss(X, Y, angles):
	"""Return loss from transforming Y into X"""
	print Y
	print X
	Y_ = transformer(Y, angles, tf.shape(X)[1:3])
	return tf.reduce_mean(tf.square(X) - tf.square(Y_))

def conv2d(X, V, b=None, strides=(1,1,1,1), padding='VALID', name='conv2d'):
    """conv2d wrapper. Supply input X, weights V and optional bias"""
    VX = tf.nn.conv2d(X, V, strides=strides, padding=padding, name=name+'_')
    if b is not None:
        VX = tf.nn.bias_add(VX, b)
    return VX

def maxpool2d(X, k=2):
    """Tied max pool. k is the stride and pool size"""
    return tf.nn.max_pool(X, ksize=[1,k,k,1], strides=[1,k,k,1], padding='VALID')

def get_weights(filter_shape, W_init=None, name='W'):
	"""Initialize weights variable with Xavier method"""
	if W_init == None:
		stddev = np.sqrt(2.0 / np.prod(filter_shape[:2]))
		W_init = tf.random_normal(filter_shape, stddev=stddev)
	return tf.Variable(W_init, name=name)

def get_weights_list(comp_shape, in_shape, out_shape, name='W'):
	"""Return a list of weights for use with equi_real_conv(). comp_shape is a
	list of the number of elements per Fourier base. For 3x3 weights use
	[3,2,2,2]. I'm going to change this to just accept 'order' and kernel size
	in future."""
	weights_list = []
	for i, cs in enumerate(comp_shape):
		shape = [cs,in_shape,out_shape]
		weights_list.append(get_weights(shape, name=name+'_'+str(i)))
	return weights_list

def get_bias_list(n_filters, order, name='b'):
	"""Return a list of biases for use with equi_real_conv()"""
	bias_list = []
	for i in xrange(order+1):
		bias = tf.Variable(tf.constant(1e-2, shape=[n_filters]), name=name+'_'+str(i))
		bias_list.append(bias)
	return bias_list

def minibatcher(inputs, targets, batch_size, shuffle=False):
	"""Input and target are minibatched. Returns a generator"""
	assert len(inputs) == len(targets)
	if shuffle:
		indices = np.arange(len(inputs))
		np.random.shuffle(indices)
	for start_idx in range(0, len(inputs) - batch_size + 1, batch_size):
		if shuffle:
			excerpt = indices[start_idx:start_idx + batch_size]
		else:
			excerpt = slice(start_idx, start_idx + batch_size)
		yield inputs[excerpt], targets[excerpt]

def save_model(saver, saveDir, sess):
	"""Save a model checkpoint"""
	save_path = saver.save(sess, saveDir + "checkpoints/model.ckpt")
	print("Model saved in file: %s" % save_path)

def rotate_feature_maps(X, im_shape):
	"""Rotate feature maps"""
	Xsh = X.shape
	X = np.reshape(X, [-1,]+im_shape)
	X_ = []
	angle = []
	for i in xrange(X.shape[0]):
		angle.append(360*np.random.rand())
		X_.append(sciint.rotate(X[i,...], angle[-1], reshape=False))
	X_ = np.stack(X_, axis=0)
	X_ = np.reshape(X_, Xsh)
	angle = np.asarray(angle)
	return X_, angle

def rotated_difference(X, Y, angle):
	for i in xrange(X.shape[0]):
		Y_ = sciint.rotate(Y[i,...], angle[-1], reshape=False)
		np.mean((X - Y_)**2)
	X_ = np.stack(X_, axis=0)

def make_parameters(n_filters, n_classes):
	weights = {
		'w1' : get_weights([3,3,1,n_filters], name='W1'),
		'w2' : get_weights([3,3,n_filters,n_filters], name='W2'),
		'w3' : get_weights([n_filters*5*5,500], name='W3'),
		'out': get_weights([500, n_classes], name='W4')
	}
	
	biases = {
		'b1': tf.Variable(tf.constant(1e-2, shape=[n_filters])),
		'b2': tf.Variable(tf.constant(1e-2, shape=[n_filters])),
		'b3': tf.Variable(tf.constant(1e-2, shape=[500])),
		'out': tf.Variable(tf.constant(1e-2, shape=[n_classes]))
	}
	return weights, biases

def get_angles(angles, batch_size):
	"""Return the transformation matrices for the spatial transformer"""
	angles = 2.*np.pi*angles/360.
	params = np.zeros((batch_size,6))
	params[:,0] = np.cos(angles)
	params[:,1] = -np.sin(angles)
	params[:,2] = 1.
	params[:,3] = np.sin(angles)
	params[:,4] = np.cos(angles)
	params[:,5] = 1.
	return params
	
##### MAIN SCRIPT #####
def run(model='conv_Z', lr=1e-2, batch_size=250, n_epochs=500, n_filters=30,
		bn_config=[False, False], trial_num='N', combine_train_val=False):
	tf.reset_default_graph()
	
	# Load dataset
	mnist_train = np.load('./data/mnist_rotation_new/rotated_train.npz')
	mnist_valid = np.load('./data/mnist_rotation_new/rotated_valid.npz')
	mnist_test = np.load('./data/mnist_rotation_new/rotated_test.npz')
	mnist_trainx, mnist_trainy = mnist_train['x'], mnist_train['y']
	mnist_validx, mnist_validy = mnist_valid['x'], mnist_valid['y']
	mnist_testx, mnist_testy = mnist_test['x'], mnist_test['y']

	# Parameters
	lr = lr
	batch_size = batch_size
	n_epochs = n_epochs
	save_step = 100		# Not used yet
	model = model
	
	# Network Parameters
	n_input = 784 	# MNIST data input (img shape: 28*28)
	n_classes = 10 	# MNIST total classes (0-9 digits)
	dropout = 0.75 	# Dropout, probability to keep units
	n_filters = n_filters
	dataset_size = 10000
	st_loss = 0.01
	
	# tf Graph input
	x = tf.placeholder(tf.float32, [batch_size, n_input])
	rx = tf.placeholder(tf.float32, [batch_size, n_input])
	y = tf.placeholder(tf.int64, [batch_size])
	learning_rate = tf.placeholder(tf.float32)
	keep_prob = tf.placeholder(tf.float32)
	phase_train = tf.placeholder(tf.bool)
	angles = tf.placeholder(tf.float32, [batch_size, 6])
	
	weights, biases = make_parameters(n_filters, n_classes)
	
	# A standard Z-convolution network
	predx, fmx = conv_Z(x, weights, biases, keep_prob, n_filters, n_classes)
	predy, fmy = conv_Z(rx, weights, biases, keep_prob, n_filters, n_classes)

	# Define loss and optimizer
	costx = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(predx, y))
	#costy = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(predy, y))
	spatial_transformer_loss = transformer_loss(fmx[3], fmy[3], angles)
	cost = costx + st_loss*spatial_transformer_loss
	optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(cost)
	
	# Evaluate model
	correct_pred = tf.equal(tf.argmax(predx, 1), y)
	accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))
			
	# Initializing the variables
	init = tf.initialize_all_variables()
	
	if combine_train_val:
		mnist_trainx = np.vstack([mnist_trainx, mnist_validx])
		mnist_trainy = np.hstack([mnist_trainy, mnist_validy])
	
	# Summary writers
	acc_ph = tf.placeholder(tf.float32, [], name='acc_')
	acc_op = tf.scalar_summary("Validation Accuracy", acc_ph)
	cost_ph = tf.placeholder(tf.float32, [], name='cost_')
	cost_op = tf.scalar_summary("Training Cost", cost_ph)
	lr_ph = tf.placeholder(tf.float32, [], name='lr_')
	lr_op = tf.scalar_summary("Learning Rate", lr_ph)
	sess = tf.Session(config=tf.ConfigProto(log_device_placement=False))
	summary = tf.train.SummaryWriter('logs/', sess.graph)
	
	# Launch the graph
	sess.run(init)
	saver = tf.train.Saver()
	epoch = 0
	start = time.time()
	# Keep training until reach max iterations
	while epoch < n_epochs:
		generator = minibatcher(mnist_trainx, mnist_trainy, batch_size, shuffle=True)
		cost_total = 0.
		acc_total = 0.
		vacc_total = 0.
		for i, batch in enumerate(generator):
			batch_x, batch_y = batch
			rot_x, angles_ = rotate_feature_maps(batch_x, [28,28])
			angles_ = get_angles(angles_, batch_size)
			
			lr_current = lr/np.sqrt(1.+epoch*(float(batch_size) / dataset_size))
			
			# Optimize
			feed_dict = {x: batch_x, rx: rot_x, y: batch_y, angles : angles_,
						 keep_prob: dropout, learning_rate : lr_current, }
			__, cost_, acc_ = sess.run([optimizer, cost, accuracy], feed_dict=feed_dict)
			cost_total += cost_
			acc_total += acc_
		cost_total /=(i+1.)
		acc_total /=(i+1.)
		
		if not combine_train_val:
			val_generator = minibatcher(mnist_validx, mnist_validy, batch_size, shuffle=False)
			for i, batch in enumerate(val_generator):
				batch_x, batch_y = batch
				# Calculate batch loss and accuracy
				feed_dict = {x: batch_x, y: batch_y, keep_prob: 1., phase_train : False}
				vacc_ = sess.run(accuracy, feed_dict=feed_dict)
				vacc_total += vacc_
			vacc_total = vacc_total/(i+1.)
		
		feed_dict={cost_ph : cost_total, acc_ph : vacc_total, lr_ph : lr_current}
		summaries = sess.run([cost_op, acc_op, lr_op], feed_dict=feed_dict)
		summary.add_summary(summaries[0], epoch)
		summary.add_summary(summaries[1], epoch)
		summary.add_summary(summaries[2], epoch)

		print "[" + str(trial_num),str(epoch) + \
			"], Minibatch Loss: " + \
			"{:.6f}".format(cost_total) + ", Train Acc: " + \
			"{:.5f}".format(acc_total) + ", Time: " + \
			"{:.5f}".format(time.time()-start) + ", Val acc: " + \
			"{:.5f}".format(vacc_total)
		epoch += 1
		
		if (epoch) % 50 == 0:
			save_model(saver, './', sess)
	
	print "Testing"
	
	# Test accuracy
	tacc_total = 0.
	test_generator = minibatcher(mnist_testx, mnist_testy, batch_size, shuffle=False)
	for i, batch in enumerate(test_generator):
		batch_x, batch_y = batch
		feed_dict={x: batch_x, y: batch_y, keep_prob: 1., phase_train : False}
		tacc = sess.run(accuracy, feed_dict=feed_dict)
		tacc_total += tacc
	tacc_total = tacc_total/(i+1.)
	print('Test accuracy: %f' % (tacc_total,))
	save_model(saver, './', sess)
	sess.close()
	return tacc_total



if __name__ == '__main__':
	run(model='conv_Z', lr=1e-3, batch_size=132, n_epochs=500,
		n_filters=10, combine_train_val=False, bn_config=[True,True,True])