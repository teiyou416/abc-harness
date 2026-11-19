# Trimmed copy of the upstream file: the model selector, a stub base-model
# block, the Bitcoin block the harness edits, and the marker that ends it.


class InputsConfig:

    """ Seclect the model to be simulated. """
    model = 3

    ''' Input configurations for the base model '''
    if model == 0:
        Binterval = 600  # base model value that must stay untouched
        Runs = 2  # Number of simulation runs

    ''' Input configurations for Bitcoin model '''
    if model == 1:
        ''' Block Parameters '''
        Binterval = 600  # Average time (in seconds)for creating a block in the blockchain
        Bsize = 1.0  # The block size in MB
        Bdelay = 0.42  # average block propogation delay in seconds, #Ref: https://example.org/ref
        Breward = 12.5  # Reward for mining a block

        ''' Transaction Parameters '''
        hasTrans = True  # True/False to enable/disable transactions in the simulator
        Ttechnique = "Light"  # Full/Light to specify the way of modelling transactions
        Tn = 10  # The rate of the number of transactions to be created per second
        # The average transaction propagation delay in seconds (Only if Full technique is used)
        Tdelay = 5.1
        Tfee = 0.000062  # The average transaction fee
        Tsize = 0.000546  # The average transaction size  in MB

        ''' Node Parameters '''
        Nn = 3  # the total number of nodes in the network
        NODES = []
        from Models.Bitcoin.Node import Node
        NODES = [Node(id=0, hashPower=50), Node(
            id=1, hashPower=20), Node(id=2, hashPower=30)]

        ''' Simulation Parameters '''
        simTime = 10000  # the simulation length (in seconds)
        Runs = 2  # Number of simulation runs

    ''' Input configurations for Ethereum model '''
    if model == 2:
        Binterval = 12.42  # Ethereum value that must stay untouched
