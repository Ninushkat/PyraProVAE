# %%
import os
import argparse
import torch.nn as nn
import torch.nn.utils
import numpy as np
from time import time
from texttable import Texttable
# Personnal imports
from learn import Learn
from data_loaders.data_loader import import_dataset
from reconstruction import reconstruction, sampling
# Import models
from models.vae_pyrapro import VaeModel, HierarchicalEncoder, HierarchicalDecoder, Decoder
from models.vae_mathieu import VAEPianoroll, EncoderPianoroll, DecoderPianoroll
from models.ae import RegressionAE, DisentanglingAE, AE
from utils import init_classic

# %%
# -----------------------------------------------------------
#
# Argument parser, get the arguments, if not on command line, the arguments are default
#
# -----------------------------------------------------------
parser = argparse.ArgumentParser(description='PyraProVAE')
# Device Information
parser.add_argument('--device', type=str, default='cpu', help='device cuda or cpu')
# Data Parameters
parser.add_argument('--midi_path', type=str, default='/Users/esling/Datasets/symbolic/', help='path to midi folder')
parser.add_argument("--test_size",  type=float, default=0.2, help="% of data used in test set")
parser.add_argument("--valid_size", type=float, default=0.2, help="% of data used in valid set")
parser.add_argument("--dataset", type=str, default="nottingham", help="maestro | nottingham | bach_chorales | midi_folder")
parser.add_argument("--shuffle_data_set", type=int, default=1, help='')
# Novel arguments
parser.add_argument('--frame_bar',      type=int, default=64,       help='put a power of 2 here')
parser.add_argument('--score_type',     type=str, default='mono',   help='use mono measures or poly ones')
parser.add_argument('--score_sig',      type=str, default='4_4',    help='rhythmic signature to use (use "all" to bypass)')
#parser.add_argument('--data_keys',      type=str, default='C',      help='transpose all tracks to a given key')
parser.add_argument('--data_normalize', type=int, default=1,        help='normalize the data')
parser.add_argument('--data_binarize',  type=int, default=1,        help='binarize the data')
parser.add_argument('--data_pitch',     type=int, default=1,        help='constrain pitches in the data')
parser.add_argument('--data_export',    type=int, default=0,        help='recompute the dataset (for debug purposes)')
parser.add_argument('--data_augment',   type=int, default=0,        help='use data augmentation')
# Model Saving and reconstruction
parser.add_argument('--model_path',     type=str, default='/slow-2/ninon/pyrapro/models_saving/entire_model/', help='path to the saved model')
parser.add_argument('--tensorboard_path', type=str, default='output/', help='path to the saved model')
parser.add_argument('--weights_path', type=str, default='/slow-2/ninon/pyrapro/models_saving/weights/', help='path to the saved model')
parser.add_argument('--figure_reconstruction_path', type=str, default='/slow-2/ninon/pyrapro/reconstruction/', help='path to reconstruction figures')
parser.add_argument('--sampling_midi', type=str, default='/slow-2/ninon/pyrapro/sampling/midi/', help='path to MIDI reconstruction from sampling')
parser.add_argument('--sampling_figure', type=str, default='/slow-2/ninon/pyrapro/sampling/figure/', help='path to visuam reconstruction from sampling')
# Model Parameters
parser.add_argument("--model", type=str, default="PyraPro", help='PyraPro | vae_mathieu | ae')
# PyraPro and vae_mathieu specific parameters: dimensions of the architecture
parser.add_argument('--enc_hidden_size', type=int, default=2048, help='do not touch if you do not know')
parser.add_argument('--latent_size', type=int, default=512, help='do not touch if you do not know')
parser.add_argument('--cond_hidden_size', type=int, default=1024, help='do not touch if you do not know')
parser.add_argument('--cond_output_dim', type=int, default=512, help='do not touch if you do not know')
parser.add_argument('--dec_hidden_size', type=int, default=1024, help='do not touch if you do not know')
parser.add_argument('--num_layers', type=int, default=2, help='do not touch if you do not know')
parser.add_argument('--num_subsequences', type=int, default=8, help='do not touch if you do not know')
parser.add_argument('--num_classes', type=int, default=8, help='number of velocity classes')
# Optimization parameters
parser.add_argument('--batch_size', type=int, default=64, help='input batch size')
parser.add_argument('--subsample', type=int, default=0, help='train on subset')
parser.add_argument('--epochs', type=int, default=150, help='number of epochs to train')
parser.add_argument('--nbworkers', type=int, default=3, help='')
parser.add_argument('--lr', type=float, default=0.001, help='learning rate')
parser.add_argument('--seed', type=int, default=1, help='random seed')
# parser.add_argument('--log-interval', type=int, default=10, help='how many batches to wait before logging training status')
# parser.add_argument('--no-cuda', action='store_true', default=False, help='disables CUDA training')
# parser.add_argument('--save-model', action='store_true', default=True, help='For Saving the current Model')
# Parse the arguments
args = parser.parse_args()

# %%
# -----------------------------------------------------------
#
# Base setup section
#
# -----------------------------------------------------------
# Sets the seed for generating random numbers
torch.manual_seed(args.seed)
np.random.seed(args.seed)
# Enable CuDNN optimization
if args.device != 'cpu':
    torch.backends.cudnn.benchmark = True
# Handling Cuda
args.cuda = not args.device == 'cpu' and torch.cuda.is_available()
args.device = torch.device(args.device if torch.cuda.is_available() else 'cpu')
# Print info
print(10 * '*******')
print('* Lovely run info:')
print('* Your great optimization will be on ' + str(args.device))
print('* Your wonderful model is ' + str(args.model))
print('* You are using the schwifty ' + str(args.dataset) + ' dataset')
print(10 * '*******')
# Handling directories
os.system('rm -rf /slow-2/ninon/pyrapro/*')

# %%
# -----------------------------------------------------------
#
# Base setup section
#
# -----------------------------------------------------------
# Data importing
print('[Importing dataset]')
train_loader, valid_loader, test_loader, train_set, valid_set, test_set, args = import_dataset(args)

# %%
# -----------------------------------------------------------
#
# Model and layers creation
#
# -----------------------------------------------------------
# Model creation
print('[Creating encoder and decoder]')
# Here select between different encoders and decoders
print('[Creating model]')
# Then select different models
if args.model == 'PyraPro':
    encoder = HierarchicalEncoder(args)
    decoder = HierarchicalDecoder(args)
    # decoder = Decoder(args)
    model = VaeModel(encoder=encoder, decoder=decoder, args=args).float()

elif args.model == 'vae_mathieu':
    encoder = EncoderPianoroll(args)
    decoder = DecoderPianoroll(args)
    model = VAEPianoroll(encoder=encoder, decoder=decoder, args=args).float()

elif args.model == 'ae':
    encoder = EncoderPianoroll(args)
    decoder = DecoderPianoroll(args)
    model = AE(encoder=encoder, decoder=decoder, encoder_dims=args.input_dim, latent_dims=args.latent_size).float()

else:
    print("Oh no, unknown model " + args.model + ".\n")
    exit()
# Send model to the device
model.to(args.device)
# Initialize the model weights
print('[Initializing weights]')
model.apply(init_classic)

# %%
# -----------------------------------------------------------
#
# Optimizer
#
# -----------------------------------------------------------
print('[Creating optimizer]')
# Optimizer
optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)
# Scheduler
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=20,
                                                       verbose=False, threshold=0.0001, threshold_mode='rel',
                                                       cooldown=0, min_lr=1e-07, eps=1e-08)
# Learning class
learn = Learn(args, train_loader=train_loader, validate_loader=valid_loader, test_loader=test_loader,
              train_set=train_set, validate_set=valid_set, test_set=test_set)

# %%
# -----------------------------------------------------------
#
# Losses functions
#
# -----------------------------------------------------------
print('[Creating criterion]')
# Losses
if args.model in ['ae', 'vae', 'wae', 'vae_flow']:
    criterion = nn.L1Loss()
elif args.model in ['PyraPro', 'vae_mathieu']:
    criterion = nn.MSELoss()
#if (args.data_binarize):
#    args.num_classes = 2
#    criterion = nn.CrossEntropyLoss()

# %%
# -----------------------------------------------------------
#
# Training loop
#
# -----------------------------------------------------------
# Initial training of the model
# learn.save(model, args, epoch=0)
# Set time
time0 = time()
# Initial test
print('[Initial evaluation]')
# learn.test(model, args, epoch=0)  # First test on randomly initialized data
print('[Starting main training]')
# Through the epochs
for epoch in range(1, args.epochs + 1, 1):
    print(f"Epoch: {epoch}")
    # Training epoch
    loss_mean, kl_div_mean, recon_loss_mean = learn.train(model, optimizer, criterion, args, epoch)
    # Validate epoch
    loss_mean_validate, kl_div_mean_validate, recon_loss_mean_validate = learn.validate(model, criterion,  args, epoch)
    # Step for learning rate
    scheduler.step(loss_mean_validate)
    # Test model
    loss_mean_test, kl_div_mean_test, recon_loss_mean_test = learn.test(model, criterion, args, epoch)
    # Save weights
    learn.save(model, args, epoch)
# -----------------------------------------------------------
#
# Evaluate stuffs
#
# -----------------------------------------------------------
    reconstruction(args, model, epoch, test_set)
    # sampling(args)
    # Track on stuffs
    print("*******" * 10)
    print('* Useful & incredible tracking:')
    t = Texttable()
    t.add_rows([['Name', 'loss mean', 'kl_div mean', 'recon_loss mean'],
                ['Train', loss_mean, kl_div_mean, recon_loss_mean],
                ['Validate', loss_mean_validate, kl_div_mean_validate, recon_loss_mean_validate],
                ['Test', loss_mean_test, kl_div_mean_test, recon_loss_mean_test]])
    print(t.draw())
    print(10 * '*******')
print('\nTraining Time in minutes =', (time() - time0) / 60)
