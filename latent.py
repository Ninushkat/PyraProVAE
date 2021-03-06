#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Jul 27 14:25:06 2020

@author: esling
"""
import os
import argparse
import torch
import torch.nn as nn
import numpy as np
import random
import matplotlib.pyplot as plt
from data_loaders.data_loader import import_dataset
from symbolic import compute_symbolic_features, features
from utils import LatentDataset, epoch_train, epoch_test, init_classic
import matplotlib.patches as patches
import matplotlib.gridspec as gridspec
import pretty_midi
from statistics import mean
import math
import seaborn as sns

#%%s
# Beautify the plots
large = 26; med = 18; small = 12
params = {'axes.titlesize': large,
          'legend.fontsize': med,
          'figure.figsize': (8, 5),
          'axes.labelsize': med,
          'axes.titlesize': med,
          'xtick.labelsize': large,
          'ytick.labelsize': med,
          'figure.titlesize': large}
plt.rcParams.update(params)
plt.style.use('seaborn-whitegrid')
sns.set_style("white")

# %% - Argument parsing
parser = argparse.ArgumentParser(description='PyraProVAE')
# Device Information
parser.add_argument('--device', type=str, default='cpu', help='device cuda or cpu')
# Data Parameters
parser.add_argument('--midi_path', type=str, default='/fast-1/mathieu/datasets', help='path to midi folder')
parser.add_argument('--full_track', type=str, default='/full_midi_track', help='path to midi folder')
parser.add_argument("--test_size", type=float, default=0.2, help="% of data used in test set")
parser.add_argument("--valid_size", type=float, default=0.2, help="% of data used in valid set")
parser.add_argument("--dataset", type=str, default="nottingham",
                    help="maestro | nottingham | bach_chorales | midi_folder")
parser.add_argument("--shuffle_data_set", type=int, default=0, help='')
# Novel arguments
parser.add_argument('--frame_bar', type=int, default=64, help='put a power of 2 here')
parser.add_argument('--score_type', type=str, default='mono', help='use mono measures or poly ones')
parser.add_argument('--score_sig', type=str, default='4_4', help='rhythmic signature to use (use "all" to bypass)')
parser.add_argument('--data_normalize', type=int, default=1, help='normalize the data')
parser.add_argument('--data_binarize', type=int, default=1, help='binarize the data')
parser.add_argument('--data_pitch', type=int, default=1, help='constrain pitches in the data')
parser.add_argument('--data_export', type=int, default=0, help='recompute the dataset (for debug purposes)')
parser.add_argument('--data_augment', type=int, default=1, help='use data augmentation')
parser.add_argument('--num_classes', type=int, default=2, help='number of velocity classes')
parser.add_argument('--subsample', type=int, default=0, help='train on subset')
parser.add_argument('--nbworkers', type=int, default=3, help='')
# Model Parameters
parser.add_argument("--model", type=str, default="vae", help='ae | vae | vae-flow | wae')
parser.add_argument("--encoder_type", type=str, default="cnn-gru",
                    help='mlp | cnn | res-cnn | gru | cnn-gru | hierarchical')
parser.add_argument("--beta", type=float, default=2., help='value of beta regularization')
parser.add_argument('--enc_hidden_size', type=int, default=512, help='do not touch if you do not know')
parser.add_argument('--latent_size', type=int, default=16, help='do not touch if you do not know')
# Output path
parser.add_argument('--output_path', type=str, default='output/', help='major path for data output')
parser.add_argument('--model_path', type=str, default='', help='path to midi folder')
# Optimization arguments
parser.add_argument('--batch_size', type=int, default=64, help='input batch size')
# Parse the arguments
args = parser.parse_args()
# Handle device
args.device = torch.device(args.device if torch.cuda.is_available() else 'cpu')

# %% ---------------------------------------------------------
#
# Load dataset and compute symbolic features
#
# -----------------------------------------------------------
# Data importing
data_variants = [args.dataset, args.score_type, args.data_binarize, args.num_classes]
args.loaders_path = args.output_path + '/loaders_'
for m in data_variants:
    args.loaders_path += str(m) + '_'
args.loaders_path = args.loaders_path[:-1] + '.th'
print('[Importing dataset]')
if not os.path.exists(args.loaders_path):
    # Import dataset from files
    train_loader, valid_loader, test_loader, train_set, valid_set, test_set, args = import_dataset(args)
    # Recall minimum pitch
    args.min_pitch = train_set.min_p
    # Compute features on all sets
    print('[Computing features]')
    train_features = compute_symbolic_features(train_loader, args)
    valid_features = compute_symbolic_features(valid_loader, args)
    test_features = compute_symbolic_features(test_loader, args)
    # Save everything as a torch object
    torch.save([train_loader, valid_loader, test_loader,
                train_set, valid_set, test_set,
                train_features, valid_features, test_features], args.loaders_path)
else:
    data = torch.load(args.loaders_path)
    train_loader, valid_loader, test_loader = data[0], data[1], data[2]
    train_set, valid_set, test_set = data[3], data[4], data[5]
    train_features, valid_features, test_features = data[6], data[7], data[8]
    # Recall minimum pitch
    args.min_pitch = train_set.min_p
    args.max_pitch = train_set.max_p

# %% ---------------------------------------------------------
#
# Load selected model
#
# -----------------------------------------------------------
print('[Importing model]')
# Infer correct model path if absent
if len(args.model_path) == 0:
    model_variants = [args.dataset, args.score_type, args.data_binarize, args.num_classes, args.data_augment,
                      args.model, args.encoder_type, args.latent_size, args.beta, args.enc_hidden_size]
    args.model_path = args.output_path
    for m in model_variants:
        args.model_path += str(m) + '_'
    args.model_path = args.model_path[:-1] + '/'
# Reload best performing model
model = torch.load(args.model_path + 'models/_full.pth', map_location=args.device)


# %% ---------------------------------------------------------
#
# Compute latent 
#
# -----------------------------------------------------------


def compute_latent(model, loader, args):
    mu_set = []
    var_set = []
    latent_set = []
    with torch.no_grad():
        for x in loader:
            # Send to device
            x = x.to(args.device, non_blocking=True)
            # Encode into model
            latent, mu, var = model.encode(x)
            latent_set.append(latent.detach())
            if args.model != 'ae':
                mu_set.append(mu.detach())
                var_set.append(var.detach())
    # Concatenate into vector
    final_latent = torch.cat(latent_set, dim=0)
    if len(mu_set) > 1:
        mu_set = torch.cat(mu_set, dim=0)
        var_set = torch.cat(var_set, dim=0)
    return final_latent, mu_set, var_set


print('[Computing latent features]')
args.latent_path = args.model_path + '/latent_'
for m in data_variants:
    args.latent_path += str(m) + '_'
args.latent_path = args.latent_path[:-1] + '.th'
if not os.path.exists(args.latent_path):
    latent_train, mu_train, var_train = compute_latent(model, train_loader, args)
    latent_valid, mu_valid, var_valid = compute_latent(model, valid_loader, args)
    latent_test, mu_test, var_test = compute_latent(model, test_loader, args)
    # Save everything as a torch object
    torch.save([latent_train, mu_train, var_train,
                latent_valid, mu_valid, var_valid,
                latent_test, mu_test, var_test], args.latent_path)
else:
    data = torch.load(args.latent_path)
    latent_train, mu_train, var_train = data[0], data[1], data[2]
    latent_valid, mu_valid, var_valid = data[3], data[4], data[5]
    latent_test, mu_test, var_test = data[6], data[7], data[8]

# %% ---------------------------------------------------------
#
# Compute decompositions on latent space
#
# -----------------------------------------------------------
from sklearn import manifold, decomposition
from mpl_toolkits.mplot3d import Axes3D


def compute_projection(dataset, target_dims=3, projection='pca'):
    orig_dims = dataset.shape[1]
    # Create decomposition
    if projection == 'pca':
        decomp = decomposition.PCA(n_components=target_dims)
    elif projection == 'tsne':
        decomp = manifold.TSNE(n_components=target_dims)
    X = decomp.fit_transform(dataset.detach())
    return X, decomp


def plot_projection(X, colors=[], name=None, output=None):
    fig = plt.figure(figsize=(16, 12))
    ax = Axes3D(fig, rect=[0, 0, .95, 1], elev=48, azim=224)
    ax.scatter(X[:, 0], X[:, 1], X[:, 2], c=colors, cmap=plt.cm.nipy_spectral, edgecolor='k')
    if name is not None:
        plt.title(name)
    if output is not None:
        plt.savefig(output)
        plt.close()


# Plots we are going to check
plot_targets = ['nb_notes', 'note_density', 'quality', 'range', 'pitch_variety', 'amount_arpeggiation',
                'direction_motion']
# Compute one full PCA on train set
_, full_pca = compute_projection(mu_train, target_dims=mu_train.shape[1])
# Compute 3D PCA on train set
z_train_pca, pca = compute_projection(mu_train)
# Apply PCA on the test set
z_test_pca = pca.transform(mu_test)
# %% Plot various feature-colored variants
for f in plot_targets:
    plot_projection(z_test_pca, colors=torch.Tensor(test_features[f]), name=f + ' - Test',
                    output='output/figures/pca_test_' + f + '.pdf')
    plot_projection(z_train_pca, colors=torch.Tensor(train_features[f]), name=f + ' - Train',
                    output='output/figures/pca_train_' + f + '.pdf')
# Compute 3D t-SNE on test set
z_test_tsne, _ = compute_projection(mu_test, projection='tsne')
# Plot various feature-colored variants
for f in plot_targets:
    plot_projection(z_test_tsne, colors=torch.Tensor(test_features[f]), name=f + ' - Test',
                    output='output/figures/tSNE_test_' + f + '.pdf')

# %% ---------------------------------------------------------
#
# Analyze latent dimensions
#
# -----------------------------------------------------------
from figures import evaluate_dimensions

# Compute combo sets
mu_full = torch.cat([mu_train, mu_valid, mu_test], dim=0)
var_full = torch.cat([var_train, var_valid, var_test], dim=0)
# Compute mean of var
var_means = torch.mean(var_full, dim=0)
print(var_means)
# Analyze the PCA latent dimensions 
evaluate_dimensions(model, test_loader, full_pca, name='output/figures/dimension_pca_')
# Analyze the latent dimensions
evaluate_dimensions(model, test_loader, latent_dims=full_pca.n_features_, name='output/figures/dimension_')


# Evaluate some translations in the latent space
# evaluate_translations(model, test_loader, latent_dims = full_pca.n_features_, name='output/figures/translation_')


# %% --------------------------------------------------------
#
# Analyze evolution of one full track in latent space
#
# -----------------------------------------------------------

def evolution_full_track(args):
    midi_files = np.array([files_names for files_names in os.listdir(args.full_track) if
                           (files_names.endswith('.midi') or files_names.endswith('.mid'))])
    for track in np.arange(start=0, stop=np.size(midi_files)):
        midi_data = pretty_midi.PrettyMIDI(args.full_track + '/' + midi_files[track])
        downbeats = midi_data.get_downbeats()
        bar_time = mean([downbeats[i + 1] - downbeats[i] for i in range(len(downbeats) - 1)])
        fs = int(args.frame_bar / round(bar_time))
        piano_roll = midi_data.get_piano_roll(fs=fs)
        full_slices = []
        for i in range(len(downbeats) - 1):
            # compute the piano-roll for one bar and save it
            sliced_piano_roll = np.array(piano_roll[:,
                                         math.ceil(downbeats[i] * fs):math.ceil(downbeats[i + 1] * fs)])
            if sliced_piano_roll.shape[1] > args.frame_bar:
                sliced_piano_roll = np.array(sliced_piano_roll[:, 0:args.frame_bar])
            elif sliced_piano_roll.shape[1] < args.frame_bar:
                continue
            print(sliced_piano_roll.shape)
            sliced_piano_roll = torch.from_numpy(sliced_piano_roll).float()
            full_slices.append(sliced_piano_roll[args.min_pitch:args.max_pitch+1].unsqueeze(0))
        full_slices = torch.cat(full_slices)    
        print(full_slices.shape)
        # Encode to latent space every slice of the track
        latent_points, _, _ = model.encode(full_slices)
        print(latent_points.shape)
        # TSNE on track
        latent_track = pca.transform(latent_points.detach())
        # Plot
        fig = plt.figure(figsize=(16, 12))
        ax = Axes3D(fig, rect=[0, 0, .95, 1], elev=48, azim=224)
        ax.scatter(z_test_pca[:, 0], z_test_pca[:, 1], z_test_pca[:, 2], c='k', cmap=plt.cm.nipy_spectral, edgecolor='k')
        ax.plot(latent_track[:, 0], latent_track[:, 1], latent_track[:, 2], c='r', linewidth=2)
        plt.title(str(midi_files[track]) + '.mid encoding in latent space')
        plt.savefig('output/figures/tracks/' + str(midi_files[track]) + '.pdf')
        plt.close()
        
args.max_pitch = train_set.max_p
args.full_track = '/Users/esling/Datasets/symbolic/Nottingham/test/'
evolution_full_track(args)

# %% ---------------------------------------------------------
#
# Latent vector basic arithmetic
#
# -----------------------------------------------------------

def arithmetic(args, dataset, fs=25, program=0):
    for i in range(10):
        x_a, x_b, x_c, x_d = None, None, None, None
        points = [x_a, x_b, x_c, x_d]
        latent = []
        for x in points:
            x = dataset[random.randint(0, len(dataset) - 1)]
            x = x.to(args.device)
            # Encode samples to the latent space
            latent.append(model.encode(x.unsqueeze(0))[0])
        [z_a, z_b, z_c, z_d] = latent
        output_a = model.decode(z_a)
        output_b = model.decode(z_b)
        output_c = model.decode(z_c)
        output_d = model.decode(z_d)
        output_diff = model.decode(z_a - z_b)
        output_add_c = model.decode(z_a - z_b + z_c)
        output_add_d = model.decode(z_a - z_b + z_d)
        fig = plt.figure(figsize=(8, 8))
        ax = Axes3D(fig, rect=[0, 0, .95, 1], elev=34, azim=224)
        ax.scatter(z_test_pca[:, 0], z_test_pca[:, 1], z_test_pca[:, 2], c='k', cmap=plt.cm.nipy_spectral, edgecolor='k')
        for z, name in [(z_a, 'A'), (z_b, 'B'), (z_c, 'C'), (z_d, 'D'), (z_a-z_b, 'A-B'), (z_a-z_b+z_c, 'A-B+C'), (z_a-z_b+z_d, 'A-B+D')]:
            z_t = pca.transform(z.detach())
            ax.text(z_t[0, 0], z_t[0, 1], z_t[0, 2], name, fontsize=18, fontweight='bold', color='r', verticalalignment='center', horizontalalignment='center')
        plt.savefig('output/figures/arithmetics_' + str(i) + '_space.pdf')
        plt.close()
        fig = plt.figure(figsize=(20, 4))
        outer = gridspec.GridSpec(1, 7, wspace=0.2, hspace=0.4)
        for count, (cur_title, cur_val) in enumerate([('A', output_a), ('B', output_b), ('C', output_c), ('D', output_d), ('A - B', output_diff), ('A - B + C', output_add_c), ('A - B + D', output_add_d)]):
            ax = plt.Subplot(fig, outer[count])
            roll = torch.argmax(cur_val[0], 0)
            notes, frames = roll.shape
            # Pad 1 column of zeros to acknowledge initial and ending events
            piano_roll = np.pad(roll.cpu().detach(), [(0, 0), (1, 1)], 'constant')
            # Use changes in velocities to find note on/note off events
            velocity_changes = np.nonzero(np.diff(piano_roll).T)
            # Keep track on velocities and note on times
            prev_velocities = np.zeros(notes, dtype=int)
            note_on_time = np.zeros(notes)
            min_pitch = np.inf
            max_pitch = 0
            cmap = plt.get_cmap('copper', 11)
            for time, note in zip(*velocity_changes):
                # Use time + 1s because of padding above
                velocity = piano_roll[note, time + 1]
                if velocity > 0:
                    if prev_velocities[note] == 0:
                        note_on_time[note] = time
                        prev_velocities[note] = 75
                else:
                    prev_velocities[note] = 0
                    rect = patches.Rectangle((note_on_time[note], note + 40 - 0.5), (time - note_on_time[note]), 1, linewidth=1.5,
                                 edgecolor='k', facecolor=cmap(count), alpha=0.8)
                    min_pitch = min(min_pitch, note + 40)
                    max_pitch = max(max_pitch, note + 40)
                    ax.add_patch(rect) 
            ax.set_ylim([min_pitch - 5, max_pitch + 5])
            ax.set_xticks(np.arange(0, 64, 16))
            ax.set_xticklabels(np.arange(1, 4, 1))
            ax.set_xlim([0, time])
            ax.set_title(cur_title)
            ax.get_xaxis().set_visible(False)
            fig.add_subplot(ax)
        plt.savefig('output/figures/arithmetics_' + str(i) + '.pdf')
        plt.close()
    # # Generate MIDI from interpolation
    # pm = pretty_midi.PrettyMIDI()
    # notes, frames = stack_interp.shape 
    # instrument = pretty_midi.Instrument(program=program)
    # # Pad 1 column of zeros to acknowledge initial and ending events
    # piano_roll = np.pad(stack_interp.cpu().detach(), [(0, 0), (1, 1)], 'constant')
    # # Use changes in velocities to find note on/note off events
    # velocity_changes = np.nonzero(np.diff(piano_roll).T)
    # # Keep track on velocities and note on times
    # prev_velocities = np.zeros(notes, dtype=int)
    # note_on_time = np.zeros(notes)
    # for time, note in zip(*velocity_changes):
    #     # Use time + 1s because of padding above
    #     velocity = piano_roll[note, time + 1]
    #     time = time / fs
    #     if velocity > 0:
    #         if prev_velocities[note] == 0:
    #             note_on_time[note] = time
    #             prev_velocities[note] = 75
    #     else:
    #         pm_note = pretty_midi.Note(
    #             velocity=prev_velocities[note],
    #             pitch=note + args.min_pitch,
    #             start=note_on_time[note],
    #             end=time)
    #         instrument.notes.append(pm_note)
    #         prev_velocities[note] = 0
    # pm.instruments.append(instrument)
    # # Write out the MIDI data
    # pm.write(args.midi_results_path + "interpolation.mid")

args.n_steps = 8
arithmetic(args, test_set, fs=25, program=0)

# %% -----------------------------------------------------------
#
# Classification section
#
# -----------------------------------------------------------

# Classifier properties
latent_size = latent_train.shape[1]
hidden_size = 256
args.lr = 1e-2
args.epochs = 100
classification_targets = ['nb_notes', 'note_density', 'quality', 'range',
                          'pitch_variety', 'amount_arpeggiation', 'direction_motion']
# Loop through all the features
for target in classification_targets:
    # Number of classes
    if features[target][1] == 'int':
        nb_classes = max(train_features[target]) + 1
    elif features[target][1] == 'float':
        nb_classes = 1
    else:
        nb_classes = 2
    # Create dataset holders
    z_train_set = LatentDataset(latent_train, train_features[target])
    z_train_loader = torch.utils.data.DataLoader(z_train_set, batch_size=64)
    z_valid_set = LatentDataset(latent_valid, valid_features[target])
    z_valid_loader = torch.utils.data.DataLoader(z_valid_set, batch_size=64)
    z_test_set = LatentDataset(latent_test, test_features[target])
    z_test_loader = torch.utils.data.DataLoader(z_test_set, batch_size=64)
    # Create simple classifier
    classifier = nn.Sequential()
    classifier.add_module('l1', nn.Linear(latent_size, hidden_size))
    classifier.add_module('b1', nn.BatchNorm1d(hidden_size))
    classifier.add_module('r1', nn.LeakyReLU())
    classifier.add_module('l2', nn.Linear(hidden_size, nb_classes))
    classifier.apply(init_classic)
    if nb_classes > 1:
        classifier.add_module('s', nn.Softmax())
    # Optimizer
    optimizer = torch.optim.Adam(classifier.parameters(), lr=args.lr, weight_decay=1e-4)
    # Scheduler
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=20,
                                                           verbose=False, threshold=0.0001, threshold_mode='rel',
                                                           cooldown=0, min_lr=1e-07, eps=1e-08)
    # Losses
    if nb_classes > 1:
        criterion = nn.NLLLoss(reduction='sum')
    else:
        criterion = nn.MSELoss(reduction='sum')
        # -----------------------------------------------------------
    # Training loop
    # -----------------------------------------------------------
    print(f'[Starting training on {target}]')
    # Set best to infinity
    cur_best_valid = np.inf
    best_test = np.inf
    # Through the epochs
    for epoch in range(1, args.epochs + 1, 1):
        # Training epoch
        loss_train = epoch_train(classifier, optimizer, criterion, z_train_loader, args)
        # Validate epoch
        loss_valid = epoch_test(classifier, optimizer, criterion, z_valid_loader, args)
        # Step for learning rate
        scheduler.step(loss_valid)
        # Test model
        loss_test = epoch_test(classifier, optimizer, criterion, z_test_loader, args)
        # Print current scores
        print(f'Epoch {epoch}  : {loss_train.item()} - {loss_valid.item()} - {loss_test.item()}')
        if loss_valid < cur_best_valid:
            cur_best_valid = loss_valid
            best_test = loss_test

if __name__ == "__main__":
    evolution_full_track(args)
