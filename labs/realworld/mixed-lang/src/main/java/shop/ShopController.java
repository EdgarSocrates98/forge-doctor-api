import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/shop")
public class ShopController {
    @GetMapping("/items/{id}")
    public Item getItem(@PathVariable("id") String id) { return null; }
}
