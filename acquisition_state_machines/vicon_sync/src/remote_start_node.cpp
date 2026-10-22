
/**
 *	This is mostly from the example from vicon.
 *
 */

#include <boost/asio/ip/address_v4.hpp>
#include <boost/asio/ip/udp.hpp>
#include <boost/system/error_code.hpp>
#include <boost/thread/pthread/mutex.hpp>
#include <opensimrt_msgs/SetFileNameSrv.h>
#include <std_srvs/Empty.h>

#include "ros/init.h"
#include "ros/rate.h"
#include "ros/ros.h"
#include <iostream>
#include <sstream>
#include <boost/program_options.hpp>
#include <boost/lexical_cast.hpp>
#include <boost/random.hpp>

#include <string>
#include <time.h>

#pragma warning( push )
#pragma warning( disable : 4242 )
#include <boost/asio.hpp>
#pragma warning( pop )

bool start, stop;
std::string dirname;
std::string filename;
std::string description;
std::string notes;
std::string remove_path_prefix, append_path_prefix;

boost::mutex my_lock;

bool do_nothing(std_srvs::Empty::Request &req, std_srvs::Empty::Response &res)
{
	//vicon stops, saves and clears one after the other, (maybe that's also what i should have done)
	//so some services will be here but doing nothing, otherwise i would need to implement the change in logic to the state machine and that would be a pain
	return true;
}
bool startRecording(std_srvs::Empty::Request &req, std_srvs::Empty::Response &res)
{
	ROS_INFO_STREAM("startRecording service called.");
	start = true;
	stop = false;
	return true;
}
bool stopRecording(std_srvs::Empty::Request &req, std_srvs::Empty::Response &res)
{
	ROS_INFO_STREAM("stopRecording service called.");
	start = false;
	stop = true;
	return true;
}
bool setNamePath(opensimrt_msgs::SetFileNameSrv::Request &req, opensimrt_msgs::SetFileNameSrv::Response &res)
{
	my_lock.unlock();
	ROS_INFO_STREAM("name " << req.name << " path:"<< req.path);
	ROS_WARN_STREAM("\n\tappend_path_prefix: " << append_path_prefix << "\n\tremove_path:"<< remove_path_prefix);
	std::string new_path = req.path;
	dirname = append_path_prefix+new_path.erase(0,remove_path_prefix.size());
	filename = req.name;
	description = req.description;
	notes = req.notes;

	ROS_INFO_STREAM("VICON_FILENAME: "<< filename <<" VICON_SAVEDIR: "<<dirname);
	my_lock.lock();
	return true;
}



int main( int argc, char *argv[] )
{
	std::string CaptureName;
	std::string CaptureNotes;
	std::string CaptureDescription;
	std::string CaptureDatabasePath;
	std::string Timecode;
	unsigned int CaptureDelayInMilliseconds = 0;
	unsigned short Port = 30;

	// Parse out the options from the command line.
	// The name and path are mandatory for both the start and stop signals.


	// services:
	//
	// start
	// stop
	//
	// modes: 
	//
	// - timecode
	// - delay
	//
	// also needs to send path and filename
	//
	// plus some description
	// plus some notes
	//
	// finally port
	//

	ros::init(argc, argv, "vicon_remote_commander");

	ros::NodeHandle nh("~");
	ros::NodeHandle n; //global nodehandle
	
	my_lock.unlock();
	nh.getParam("remove_path_prefix",remove_path_prefix);
	nh.getParam("append_path_prefix",append_path_prefix);
	ROS_WARN_STREAM("\n\tappend_path_prefix: " << append_path_prefix << "\n\tremove_path:"<< remove_path_prefix);

	my_lock.lock();

	int port_port;
	nh.param<int>("port", port_port, 30);

	std::string vicon_ip;
	nh.param<std::string>("vicon_ip", vicon_ip, "192.168.1.102");

	bool use_broadcast;
	nh.param("use_broadcast", use_broadcast, false);

	Port = (unsigned short)port_port;
	ROS_INFO_STREAM("Using port:" << Port);

	auto startRecordingSrv 	= nh.advertiseService("start_recording", startRecording);
	auto stopRecordingSrv 	= nh.advertiseService("stop_recording", 	stopRecording);
	auto setNamePathSrv 		= nh.advertiseService("set_name_and_path", 	setNamePath);

	//they exist but do nothing
	auto writeSrv 		= nh.advertiseService("write", do_nothing);
	auto writeStoSrv 	= nh.advertiseService("write_sto", do_nothing);
	auto clearLoggersSrv 	= nh.advertiseService("clear_loggers", do_nothing);

	bool mode_timecode =false;
	nh.param("mode_timecode", mode_timecode, false);

	bool mode_delay =true;
	nh.param("mode_delay", mode_timecode, true);

	int delay_ms = 20;
	nh.param("delay_ms", delay_ms, 20);
	CaptureDelayInMilliseconds = (unsigned int)delay_ms;

	int epoch_start = 20;
	nh.param("epoch_start",epoch_start , 20); //to keep the consistency with savernode
						  //Timecode = std::to_string(epoch_start);
	ROS_WARN_STREAM("epoch_start, aka Timecode, is not implemented yet!!!");


	ros::Rate r(10);

	// Seed the random number with the time.
	boost::rand48 Random( 100000 );
	Random.seed( static_cast< boost::rand48::result_type >( time(0) ) );

	// The packet ID is selected randomly.
	// Packets with duplicate ID's are ignored by Nexus.

	//.Set up ASIO for UDP broadcast.
	boost::asio::io_service Service;

	// Create and open socket.
	boost::asio::ip::udp::socket Socket( Service );

	boost::system::error_code Error = Socket.open( boost::asio::ip::udp::v4(), Error );

	if( !Error )
	{
		// Successfully opened the socket.
		// Set to broadcast.
		Socket.set_option( boost::asio::ip::udp::socket::reuse_address(true) );
		Socket.set_option( boost::asio::socket_base::broadcast(true) );

		boost::asio::ip::udp::endpoint remoteendpoint( boost::asio::ip::address::from_string(vicon_ip), Port );


		if(use_broadcast)
		{
			remoteendpoint = boost::asio::ip::udp::endpoint(boost::asio::ip::address_v4::broadcast(), Port);
		}
		ROS_INFO_STREAM("Setting endpoint to " << remoteendpoint.address().to_string());

		// Build up XML contents of the broadcast message.


		while(ros::ok()){

			std::ostringstream Stream;


			CaptureName = filename;
			CaptureDatabasePath = dirname;
			CaptureNotes = notes;
			CaptureDescription = description;


			const unsigned int CaptureID = Random();
			if(start || stop){
				// Start capture.
				if( start )
				{
					ROS_INFO_STREAM("reached start");
					start= false;
					Stream << "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>" << std::endl;
					Stream << "<CaptureStart>" << std::endl;
					Stream << "  <Name VALUE=\"" << CaptureName << "\"/>" << std::endl;
					if( !CaptureNotes.empty() )
						Stream << "  <Notes VALUE=\"" << CaptureNotes << "\"/>" << std::endl;
					if( !CaptureDescription.empty() )
						Stream << "  <Description VALUE=\"" << CaptureDescription << "\"/>" << std::endl;
					if( !Timecode.empty() )
						Stream << "  <TimeCode VALUE=\"" << Timecode << "\"/>" << std::endl;
					Stream << "  <DatabasePath VALUE=\"" << CaptureDatabasePath << "\"/>" << std::endl;
					Stream << "  <Delay VALUE=\"" << CaptureDelayInMilliseconds << "\"/>" << std::endl;
					Stream << "  <PacketID VALUE=\"" << CaptureID << "\"/>" << std::endl;
					Stream << "</CaptureStart>" << std::endl;
				}

				// Stop capture.
				if( stop )
				{
					ROS_INFO_STREAM("reached stop");
					stop = false;
					Stream << "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>" << std::endl;
					Stream << "<CaptureStop>" << std::endl;
					Stream << "  <Name VALUE=\"" << CaptureName << "\"/>" << std::endl;
					Stream << "  <DatabasePath VALUE=\"" << CaptureDatabasePath << "\"/>" << std::endl;
					if( !Timecode.empty() )
						Stream << "  <TimeCode VALUE=\"" << Timecode << "\"/>" << std::endl;
					Stream << "  <PacketID VALUE=\"" << CaptureID << "\"/>" << std::endl;
					Stream << "</CaptureStop>" << std::endl;
				}

				std::string String( Stream.str() );

				ROS_INFO_STREAM("string" << String);
				// Send message.
				// Buffer must contain terminating 0.
				Socket.send_to( boost::asio::buffer( String.c_str(), String.size() + 1 ), remoteendpoint );
			}
			ros::spinOnce();
			r.sleep();

		}


		boost::system::error_code close_return_value = Socket.close( Error );

		if (close_return_value)
			std::cout << "Something weird happened" << close_return_value.value() << std::endl;
	}

	return Error.value();
}
