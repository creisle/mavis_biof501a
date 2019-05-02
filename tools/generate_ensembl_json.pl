#!/projects/trans_scratch/software/perl/perl-5.20.3/bin/perl

$|++;

=pod

this script is for pull annotation information from an ensembl api
and outputting a json annotations file which can be read by mavis

optionally takes two additional tab delimited files

HUGO_ENSEMBL_MAPPING: this is a tab delimited file which must have two columns
1. ensid: the ensembl id
2. hugo: a semi-colon delimited list of hugo gene symbols

BEST_TRANSCRIPTS: this is a mapping of gene ids to the preferred transcript for annotations. It must have the following two columns
ex. /gsc/resources/annotation/ensembl/transcript_info/production/ensembl_best_transcript.tsv
1. Ensembl_Gene_ID: the ensembl gene id
2. Ensembl_Transcript_ID: the ensembl transcript id


To start the script you must set your environment variables first

export ENSEMBL_HOST=<HOSTNAME>
export ENSEMBL_PASS=<PASSWORD>
export ENSEMBL_USER=<USERNAME>
export ENSEMBL_PORT=<PORT>

=cut

use strict;
use warnings;
use Cwd;
use Cwd 'abs_path';
use File::Basename;
use Getopt::Long;
use Bio::EnsEMBL::Registry;
use Bio::EnsEMBL::ApiVersion;
use Bio::EnsEMBL::ArchiveStableId;
use Try::Tiny;
use POSIX qw(strftime);
use TSV;
use JSON;


my $registry;
my $_version = '1.0.0';
my $_program = basename(__FILE__);
my $_install = dirname(abs_path(__FILE__));

main();

sub main
{
    my $outputfile;
    my $best_transcript_file = $ENV{'BEST_TRANSCRIPTS'};
    if (! defined $best_transcript_file) {
        $best_transcript_file = "";
    }
    my $option_check = GetOptions(
        "output=s" => \$outputfile,
        "best_transcript_file=s" => \$best_transcript_file,
    );

    my $database_information =  {
        -host => $ENV{'ENSEMBL_HOST'},
        -user => $ENV{'ENSEMBL_USER'},
        -port => $ENV{'ENSEMBL_PORT'},
        -pass => $ENV{'ENSEMBL_PASS'}
    };

    my $help_message = <<"END_MESSAGE";
usage:
    $_program --output OUTPUT_FILE [--best_transcript_file BEST_TRANSCRIPT_FILE] [--hugo_mapping_file HUGO_MAPPING_FILE]

required arguments:

    output:
        path to the output json file where results will be written

optional arguments:

    best_transcript_mapping:
        path to the best transcripts file (default: $best_transcript_file)
END_MESSAGE

    # set up the default filenames
    die "$help_message\n\nerror: required argument --output not provided" if ! defined $outputfile;

    $registry = 'Bio::EnsEMBL::Registry';
    $registry->load_registry_from_db(%$database_information);

    my %best_transcript_mapping = ();
    if ("$best_transcript_file" ne "") {
        my @required_column_names = ('Ensembl_Gene_ID', 'Ensembl_Transcript_ID');
        print "loading: $best_transcript_file\n";
        my ($header, $rows) = TSV::parse_input($best_transcript_file, \@required_column_names);

        while (my $row = shift @$rows)
        {
            my $ensid = $row->{'Ensembl_Gene_ID'};
            my $transcript = $row->{'Ensembl_Gene_ID'};
            $best_transcript_mapping{$ensid} = $transcript;
        }
    }
    # load all the different transcripts
    my $transcript_adaptor = $registry->get_adaptor('human', 'core', 'gene');
    my @glist = @{$transcript_adaptor->fetch_all()};
    my $counter = 1;
    my $total = scalar @glist;
    my $interval = $total / 100;

    my %all_domains = ();
    my $time = localtime();
    my $jsons = {
        "best_transcript_file" => $best_transcript_file,
        "ensembl_version" => software_version(),
        "generation_time" => "$time",
        "script" => $_program,
        "script_version" => $_version,
        "genes" => []
    };
    print "loading $total genes\n";
    while ( my $gene = shift @glist )
    {
        print ".";
        my @tlist = @{$gene->get_all_Transcripts()};
        my $gid = $gene->stable_id();

        # get all hugo aliases for this ensembl gene
        my $hugo = "";

        # use the ensembl hugo name if not otherwise given
        if (defined $gene->external_name()) {
            $hugo = $gene->external_name();
        }

        my $gjson = {
            "name" => $gid,
            "aliases" => $hugo,
            "transcripts" => [],
            "chr" => $gene->seq_region_name(),
            "start"=> $gene->start(),
            "end" => $gene->end(),
            "strand" => $gene->strand()
        };


        my $best_transcript = "";
        if ( exists $best_transcript_mapping{$gid} and defined $best_transcript_mapping{$gid}){
            $best_transcript = $best_transcript_mapping{$gid};
        } else {
            # use the canonical transcript as 'best' if not otherwise specified
            $best_transcript = $gene->canonical_transcript()->stable_id();
        }

        while ( my $t = shift @tlist )
        {
            my $tid = $t->stable_id();
            my $best = JSON::false;

            if ($best_transcript eq $tid){
                $best = JSON::true;
            }

            my $tjson = {
                "name" => $tid,
                "is_best_transcript" => $best,
                "exons" => [],
                "start" => $t->start(),
                "end" => $t->end(),
                "aliases" => [],
                "cdna_coding_start" => $t->cdna_coding_start(),
                "cdna_coding_end" => $t->cdna_coding_end(),
                "domains" => []
            };
            
            
            my $s_obj = $t->seq();
            my $s = $s_obj->seq();
            my $cds_start = $t->cdna_coding_start();
            my $cds_end = $t->cdna_coding_end();
            if ( !defined $cds_start || !defined $cds_end ){
                next;
            }
            # get all the refseq aliases for this ensembl transcript
            my @arr = @{$t->get_all_xrefs()};
            my @refseq = ();
            while (my $x  = shift @arr )
            {
                if ( ! ( $x->dbname() =~ /^RefSeq.*/ ) ){
                    next;
                }
                push(@{$tjson->{"aliases"}}, $x->display_id());
            }
            # get the translation start and end
            # get the domain coordinates (in amino-acids)
            # now add all of the domains
            my @domain_list = @{ $t->translation()->get_all_DomainFeatures() };
            my $domain_hash = {};
            for my $dom (@domain_list)
            {
                my $key = $dom->display_id(); # ensembl domain regions are split, group by display id
                my $curr = {
                    "regions" => [],
                    "desc" => $dom->idesc(),
                    "name" => $key
                };

                if(! exists $domain_hash->{$key})
                {
                    $domain_hash->{$key} = $curr;
                } else {
                    $curr = $domain_hash->{$key};
                }
                my $region = {"start" => $dom->start(), "end" => $dom->end() };
                push(@{$curr->{"regions"}},  $region);
            }
            foreach my $val (values %$domain_hash){
                push(@{$tjson->{"domains"}}, $val)
            }

            my @exon_list = @{ $t->get_all_Exons() };
            for my $ex (@exon_list)
            {
                my $exj = {
                    "start" => $ex->start(),
                    "end" => $ex->end(),
                    "name" => $ex->stable_id()
                };
                push(@{$tjson->{"exons"}}, $exj);
            }
            push(@{$gjson->{"transcripts"}}, $tjson);
        }
        if (scalar @{$gjson->{"transcripts"}} > 0){
            push(@{$jsons->{"genes"}}, $gjson);
            $counter = $counter + 1;
        }
    }
    open(my $fh, ">", $outputfile) or die "[ERROR] Could not open outputfile $outputfile\n";
    print "\nwriting: $outputfile\n";
    print $fh encode_json $jsons;
    close $fh;
    print "[$_program] [COMPLETE] status: Complete!\n";
}

