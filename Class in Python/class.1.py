class person:
    def __init__(self,name):
        self.name=name
        #self.age=age
    def say_hello(self):
        print("hello {} !".format(self.name))   

adam = person('Adam')   
adam.say_hello()  