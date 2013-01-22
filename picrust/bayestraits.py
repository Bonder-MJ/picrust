#!/usr/bin/env python
# File created on 15 Jul 2011
from __future__ import division

"""
Application controlller for the BayesTraits ancestral state reconstruction program
"""



__author__ = "Jesse Zaneveld"
__copyright__ = "Copyright 2011-2013, The PICRUSt Project"
__credits__ = ["Jesse Zaneveld"]
__license__ = "GPL"
__version__ = "0.9.0"
__maintainer__ = "Jesse Zaneveld"
__email__ = "zaneveld@gmail.com"
__status__ = "Development"

from time import sleep
from os.path import abspath
from collections import defaultdict
from cogent import LoadTree
from cogent.util.option_parsing import parse_command_line_parameters, make_option
from cogent.app.parameters import ValuedParameter, FlagParameter, \
       MixedParameter
from cogent.app.util import CommandLineApplication, FilePath, system, \
       CommandLineAppResult, ResultPath, remove, ApplicationError
from subprocess import Popen,PIPE
from datetime import datetime

script_info = {}
script_info['brief_description'] = "An application controller for the BayesTraits program (Pagel & Meade)"
script_info['script_description'] = ""
script_info['script_usage'] = [("","","")]
script_info['output_description']= "Outputs 1) A table of reconstructions 2)A log file"
script_info['required_options'] = [\
  make_option('-t','--input_tree',type="existing_filepath",help='the input tree file in Newick format'),\
  make_option('-d','--input_trait_data',type="existing_filepath",help='the input trait table in Trait Table format')]
script_info['optional_options'] = [\
 # Example optional option
 make_option('--debug',action="store_true",default=False,help='display verbose output [default: %default]')\
]
script_info['version'] = __version__
script_info['help_on_no_arguments'] = False



class BayesTraits(CommandLineApplication):
    """BayesTraits application Controller"""

    _command = 'BayesTraits'
    _input_handler = '_input_as_lines'
    _parameters ={}
    _suppress_stdout = False
    _suppress_stderr = False




    def _input_as_lines(self,data):
        """Parses a list of treefile, traitfile, commands
        The lines must in the following order: 
        tree_file: path to NEXUS tree file
        trait_file: path to NEXUS trait file
        script_commands
        """
        tree_filepath = abspath(data[0])
        trait_table_filepath = abspath(data[1])
        script= data[2]
        argument_template = "%s %s <'%s'" 
        arguments = argument_template % (tree_filepath,trait_table_filepath,script)
        #self._command = " ".join([self._command,arguments])
    
        return arguments

    def _get_result_paths(self,data):
        """Specifies result paths for BayesTraits output files
        
        The only file created is a log file.
        By default this is named for the trait table data.
        
        """
        
        tree_file,traits_file,script_file = data
        result = {}
        result["logfile"]= ResultPath(self.WorkingDir+traits_file+".log.txt")
        return result



def make_bayestraits_script(tree, translation_dict = {}, method = 'multistate',\
        analysis_method = "ml",comments=True,single_rate=False):
    """Generate an annotated bayestrait script for stdin
    
    BayesTraits is usually interactive, but for high-throughput applications
    scripts can be passed through stdin.

    This function generates these scripts, optionally including as comment
    lines the stdout typically produced by BayesTraits so that the input 
    choices make sense.

    tree - a PyCognet PhyloNode object

    translation_dict - a dictionary translating between tip names on the tree
    and translated node names as they will appear in BayesTraits (usually tip names
    are mapped to integers)
    
i   method - as a string:  'multistate',
      'discrete_independent', 'discrete_dependent','continuous_random_walk'
    'continuous_directional','continuous_regression'

    analysis_method - as a string: 'ml' or 'mcmc'.  ML is Maximum Likelihood, MCMC is Markov Chain 
    Monte Carlo (for Bayesian analysis).  Note that if MCMC is chosen
    other parameters should be set (burnin, sample, iterations)
 
    comments - set to False to prevent addition of comment lines.
    
    """
    script_lines = []
    header = "#BayesTraits script (autogenerated)"
    
    method_menu = """#Select method.  methods are:
    #1)      MultiState. 
    #2)      Discrete: Independent model 
    #3)      Discrete: Dependent model 
    #4)      Continuous: Random Walk (Model A) 
    #5)      Continuous: Directional (Model B) 
    #6)      Continuous: Regression """
    
    if comments:
        script_lines.extend([header,method_menu])

    method_to_number = {'multistate':'1',\
            'discrete_independent':'2',\
            'discrete_dependent':'3',\
            'continuous_random_walk':'4',\
            'continuous_directional':'5',\
            'continuous_regression':'6'}

    method_response =\
      method_to_number.get(method,"method not supported")

    if method_response == "method not supported":
        raise ValueError(method_response)

    # Add our response to the first query
    script_lines.append(str(method_response))
    
    analysis_method_menu = \
        """#Select the analysis method to use. 
        #1)      Maximum Likelihood. 
        #2)      MCMC"""
    
    if comments:
        script_lines.append(analysis_method_menu)
    
    analysis_method_to_number = {'ml':'1',\
            'mcmc':'2'}

    analysis_method_response = \
      analysis_method_to_number.get(analysis_method,"analysis method not supported")
    
    if analysis_method_response == "analysis method not supported":
        raise ValueError(analysis_method_response)
    
    #Add our response to the second query
    script_lines.append(analysis_method_response)
    
    #
    if single_rate:
        if comments:
            script_lines.append("#Restrict to a single rate")
        #set to 0 to 1 rate
        script_lines.append("RestrictAll q01")

        

    #Add commands to reconstruct parent nodes
    if comments:
        script_lines.append("#Reconstruct parent nodes for each tip")

    add_mrca_cmds = get_bt_addmrca_commands(tree,translation_dict)
    script_lines.extend(add_mrca_cmds)
    
    script_lines.append("run")
    script_lines = [l+"\n" for l in script_lines]

    return script_lines

def get_bt_addmrca_commands(tree,translation_dict={}):
    """Get the BayesTraits commands to reconstruct the parent of each tree tip
    
    translation_dict -- a dictionary mapping between the names on the 
    tree and the names as they will appear in BayesTraits.  For example,
    names are typically mapped to numbers using the NEXUS translate block.

    If this is empty, names are assumed to be the same between the tree
    and BayesTraits
    """
    cmd_template = "AddMRCA %s %s\n"
    commands = ["#Add nodes to analyze\n"]
    for tip in tree.iterTips():
        
        #First name the node that will be reconstructed
        anc_node_name = "parent_of_%s" % tip.Name

        sibling_groups = [sg for sg in tip.Parent.childGroups()]
        sibling_names = []
        for group in sibling_groups:
            #print "Group:",group
            for entry in group:
                #print "Entry:",entry
                if entry.isTip():
                    #print "IsTip, adding name: %s" % entry.Name
                    sibling_names.append(entry.Name)
                else:

                     group_tip_names = [t.Name for t in entry.iterTips()]
                     #print "Group_tip_names:",group_tip_names
                     sibling_names.extend(group_tip_names)
        #print "sibling_names:",sibling_names
        translated_sibling_names = \
         [translation_dict.get(s,s) for s in sibling_names]  
        

        if not translated_sibling_names:
            raise ValueError("No sibling names found!")

        cmd_params = " ".join(map(str,translated_sibling_names))
        new_command = cmd_template %(anc_node_name,cmd_params)
        commands.append(new_command)

    return commands

def predict_bayestraits_output_file(table_filepath):
    """Predict the output files bayestraits will produce given input"""
    return table_filepath+".log.txt"


def parse_reconstruction_output_from_string(output_str):
    """Wrapper for parse_reconstruction_output taking a single str"""
    lines = output_str.split("\n")
    #print "Lines into parser:"
    #for i,line in enumerate(lines):
    #    print i,line[:min(50,len(line))],"..."
    return parse_reconstruction_output(lines)

def parse_reconstruction_output(lines):
    """Parse the reconstructed values from a bayestraits log file
    lines -- lines of the BayesTraits log file
    tips -- the tips of the tree for which we would like to extract


    NOTE:  for now this only works for the case where you are
    Reconstructing traits using ML.  Other cases will be added
    later as needed

    Further, this assumes that the log file was constructed
    using the addMRCA node script, and that each internal
    MRCA node will have the label 'parent_of_x' where x is 
    a tree tip.
    """
    reconstructions = {}
    # Start with a very minimal parsing of just the results
    start_of_header_line = "Tree No\tLh"
    header_parsed = False
    
    per_tree_results = defaultdict(dict)
    
    all_nodes = []
    all_characters = []
    
    states_by_character = defaultdict(list)
    print "Got %i lines...",len(lines)
    for line in lines:
        #Always skip blank lines
        if not line:
            continue 
        if not header_parsed and \
           not line.startswith(start_of_header_line):
            
            continue
         
        fields = line.split("\t")
        if not header_parsed:
            field_mapping = {}
            for i,field in enumerate(fields):
                if field == "Tree No":
                    field_mapping["tree_number"]=i
                elif field == "Lh":
                    field_mapping["likelihood"]=i
                elif field.startswith("q"):
                    field_mapping["rate_%s" % field] = i
                else:
                    #In a reconstructed header node field
                    if not field.strip():
                        continue #skip header field
                    
                    print "Field:",field,"."
                    node,character_str,state_str = \
                      field.split("-")
                    
                    node = node.strip()
                    character = int(character_str.split("(")[1].split(")")[0])
                    state = state_str.split("(")[1].split(")")[0]
                    #print "Field:", field
                    #print "Node:", node
                    #print "Character:",character
                    #print "State:",state
                    field_mapping["%s_%s_%s" %(node,character,state)] = i
                    
                    if node not in all_nodes:
                        all_nodes.append(node)
                    if character not in all_characters:
                        all_characters.append(character)
                    if state not in states_by_character[character]:
                        states_by_character[character].append(state)

                     
            header_parsed = True
            continue

        #If we have parsed header, start reaading lines
        data_fields = line.split("\t")
        tree_number = data_fields[field_mapping["tree_number"]]
        likelihood = data_fields[field_mapping["likelihood"]]
        per_tree_results[int(tree_number)]['likelihood'] = float(likelihood)
        
        
        output_header = "#"+"\t".join(["Trait"]+[character for character in map(str,sorted(all_characters))])
        output_lines = [output_header]
        for node in sorted(all_nodes):
            curr_fields = [node]
            for character in sorted(map(int,all_characters)):
                ml_state = (None,0.0)
                #print "Current character:",character
                #print "Possible states:",states_by_character[character]
                for state in sorted(states_by_character[character]):
                    data_desired = "_".join(map(str,[node,character,state]))
                    prob = data_fields[field_mapping[data_desired]]
                    if float(prob) > ml_state[1]:
                        ml_state = (state,float(prob))
                    #print "\t",node,character,state,prob,"curr_best:",ml_state[1]    
                #print node, character, ml_state[0],ml_state[1]
                curr_fields.append("|".join(map(str,[ml_state[0],ml_state[1]])))
            output_lines.append("\t".join(curr_fields))
        return [l+"\n" for l in output_lines]    

    return per_tree_results

def main():
    option_parser, opts, args =\
       parse_command_line_parameters(**script_info)
    start_time = datetime.now() 
    
    t = LoadTree(opts.input_tree)
    translation_dict = {}
    for i,tip in enumerate(t.iterTips()):
        translation_dict[tip.Name] = i

    single_rate = False

    #Generate commands telling BayesTraits which nodes to reconstruct
    bayestraits_commands = make_bayestraits_script(t,translation_dict,comments=False,single_rate=single_rate)
    

    #TODO: make this dynamic
    #Temporarily assuming there is a nexus file available
    nexus_fp = opts.input_tree.rsplit(".",1)[0] +".nexus" 
    command_fp = "./bayestraits_commands.txt"
    path_to_bayestraits = "../"
    outfile = "./bayestrait_reconstruction.trait_table" 
    command_file = open(command_fp,"w+")
    command_file.writelines(bayestraits_commands)
    command_file.close()

    command_file = open(command_fp,"U")

    bayestraits=BayesTraits()
    bayestraits_result = bayestraits(data=(nexus_fp,opts.input_trait_data,command_fp))
    #print "StdOut:",result["StdOut"].read()
    print "StdErr:",bayestraits_result["StdErr"].read()
    print "Return code:",bayestraits_result["ExitStatus"] 
    
    results = parse_reconstruction_output(bayestraits_result['StdOut'].readlines())
    #print "Reconstructions:",results

    #Reconstruction results
    f = open(outfile,"w+")
    f.writelines(results)
    f.close()

    end_time = datetime.now()
    print "Start time:", start_time
    print "End time:",end_time
    print "Time to reconstruct:", end_time - start_time
    bayestraits_result.cleanUp()

if __name__ == "__main__":
    main()
